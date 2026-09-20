"""Tests for the Glue entry point that runs the Silver DQ gate (PR-033).

The entry point itself is thin — `loteria.dq.runner` does the work and PR-032 covers it.
What is tested here is the part that only exists in production and therefore has no other
way of being checked: the translation between Glue's calling convention and the library,
and the two things the Step Function depends on.

The Step Function's contract is exactly two facts:
  1. bad Silver makes this process exit non-zero, and
  2. the message it exits with names what broke.

(2) is not cosmetic. It is the string Glue reports as `ErrorMessage`, which the state
machine's `Catch` pastes into the SNS alert. If it degrades to "DQ failed", the alert stops
being actionable and the gate's value drops to "something is wrong somewhere".

Note the module is importable without `awsglue` installed — that is deliberate (see the
module docstring) and is what makes this file possible at all.
"""

from __future__ import annotations

import logging

import pytest

from loteria.dq.glue_entrypoint import (
    OPTIONAL_ARGS,
    REQUIRED_ARGS,
    SilverDataQualityFailed,
    main,
    parse_args,
)
from loteria.dq.runner import (
    MAX_SUMMARIZED_FAILURES,
    DQReport,
    ExpectationOutcome,
    SilverDatasetEmpty,
    SuiteOutcome,
    format_report,
    summarize_failures,
)

BUCKET = "lottery-partitioned-storage-prod"


def outcome(suite: str, *results: ExpectationOutcome, rows: int = 10) -> SuiteOutcome:
    return SuiteOutcome(suite=suite, dataset=suite, rows=rows, files=2, results=list(results))


def passing(name: str = "expect_column_values_to_not_be_null") -> ExpectationOutcome:
    return ExpectationOutcome(name, "numero_sorteo", True, 0, 0.0)


def failing(
    name: str = "expect_column_values_to_be_unique",
    column: str = "numero_sorteo",
    count: int | None = 4,
) -> ExpectationOutcome:
    return ExpectationOutcome(name, column, False, count, 3.5)


# ==========================================================================================
# Argument parsing
# ==========================================================================================
class TestParseArgs:
    def test_reads_the_space_separated_form_glue_actually_sends(self):
        args = parse_args(["script.py", "--PARTITIONED_BUCKET", BUCKET])
        assert args["PARTITIONED_BUCKET"] == BUCKET

    def test_reads_the_equals_form_too(self):
        args = parse_args(["script.py", f"--PARTITIONED_BUCKET={BUCKET}"])
        assert args["PARTITIONED_BUCKET"] == BUCKET

    def test_ignores_the_arguments_glue_adds_on_its_own(self):
        """Glue hands a Spark job --JOB_NAME, --job-language and the logging flags.

        A positional or strict parser would choke on them. This is why the job keeps working
        when AWS adds another one.
        """
        args = parse_args(
            [
                "script.py",
                "--JOB_NAME",
                "loteria-silver-dq-prod",
                "--enable-continuous-cloudwatch-log",
                "true",
                "--PARTITIONED_BUCKET",
                BUCKET,
                "--job-language",
                "python",
            ]
        )
        assert args["PARTITIONED_BUCKET"] == BUCKET
        assert "JOB_NAME" not in args

    def test_optional_arguments_are_simply_absent_when_not_passed(self):
        """The reason this does not use ``awsglue.utils.getResolvedOptions``.

        That helper raises for any name in its list that was not supplied, so an argument
        that is genuinely optional cannot go through it.
        """
        args = parse_args(["script.py", "--PARTITIONED_BUCKET", BUCKET])
        assert not any(name in args for name in OPTIONAL_ARGS)

    def test_optional_arguments_are_read_when_present(self):
        args = parse_args(
            [
                "script.py",
                "--PARTITIONED_BUCKET",
                BUCKET,
                "--SILVER_PREFIX",
                "silver_copy/",
                "--CORRELATION_ID",
                "exec-123",
            ]
        )
        assert args["SILVER_PREFIX"] == "silver_copy/"
        assert args["CORRELATION_ID"] == "exec-123"

    def test_a_missing_required_argument_fails_fast_and_says_which(self):
        with pytest.raises(SystemExit) as exc:
            parse_args(["script.py", "--SILVER_PREFIX", "silver/"])
        assert "PARTITIONED_BUCKET" in str(exc.value)

    def test_a_flag_with_no_value_is_not_silently_accepted(self):
        """``--PARTITIONED_BUCKET`` as the last token has nothing after it to read."""
        with pytest.raises(SystemExit):
            parse_args(["script.py", "--PARTITIONED_BUCKET"])

    def test_required_and_optional_names_do_not_overlap(self):
        assert not set(REQUIRED_ARGS) & set(OPTIONAL_ARGS)


# ==========================================================================================
# The gate's contract with the Step Function
# ==========================================================================================
class TestGateBehaviour:
    """`main` is exercised with `run_dq` patched: the real thing is PR-032's job."""

    def _patch_run(self, monkeypatch, result):
        seen = {}

        def fake_run_dq(bucket, silver_prefix):
            seen["bucket"] = bucket
            seen["silver_prefix"] = silver_prefix
            if isinstance(result, Exception):
                raise result
            return result

        monkeypatch.setattr("loteria.dq.runner.run_dq", fake_run_dq)
        return seen

    def test_a_clean_silver_layer_returns_quietly(self, monkeypatch, capsys):
        report = DQReport(suites=[outcome("silver_sorteos", passing())])
        self._patch_run(monkeypatch, report)

        main(["script.py", "--PARTITIONED_BUCKET", BUCKET])

        assert "DQ RESULT: PASS" in capsys.readouterr().out

    def test_a_failed_expectation_raises_so_the_glue_run_fails(self, monkeypatch):
        report = DQReport(suites=[outcome("silver_premios", passing(), failing())])
        self._patch_run(monkeypatch, report)

        with pytest.raises(SilverDataQualityFailed):
            main(["script.py", "--PARTITIONED_BUCKET", BUCKET])

    def test_the_failure_message_names_the_suite_expectation_and_column(self, monkeypatch):
        """The whole point of the gate's alert. Guard this one hard.

        This string becomes Glue's ErrorMessage, which the Step Function's Catch pastes into
        the SNS body. "Silver DQ failed" alone sends the owner to the console.
        """
        report = DQReport(
            suites=[outcome("silver_premios", failing("expect_column_values_to_be_unique"))]
        )
        self._patch_run(monkeypatch, report)

        with pytest.raises(SilverDataQualityFailed) as exc:
            main(["script.py", "--PARTITIONED_BUCKET", BUCKET])

        message = str(exc.value)
        assert "silver_premios" in message
        assert "expect_column_values_to_be_unique" in message
        assert "numero_sorteo" in message

    def test_the_failure_message_says_gold_was_not_built(self, monkeypatch):
        """The reassuring half. A DQ alert that only says "failed" reads like data loss."""
        report = DQReport(suites=[outcome("silver_sorteos", failing())])
        self._patch_run(monkeypatch, report)

        with pytest.raises(SilverDataQualityFailed) as exc:
            main(["script.py", "--PARTITIONED_BUCKET", BUCKET])
        assert "Gold was NOT built" in str(exc.value)

    def test_the_full_verdict_is_printed_even_when_it_fails(self, monkeypatch, capsys):
        """The one-line summary goes to SNS; the whole report has to reach the job log."""
        report = DQReport(
            suites=[
                outcome("silver_sorteos", passing()),
                outcome("silver_premios", failing()),
            ]
        )
        self._patch_run(monkeypatch, report)

        with pytest.raises(SilverDataQualityFailed):
            main(["script.py", "--PARTITIONED_BUCKET", BUCKET])

        out = capsys.readouterr().out
        assert "[PASS] silver_sorteos" in out
        assert "[FAIL] silver_premios" in out

    def test_missing_silver_is_reported_as_wiring_not_as_bad_data(self, monkeypatch):
        """The distinction the CLI draws with EXIT_NO_DATA, preserved for the alert.

        "There is no Silver data" means a wrong bucket or a transformer that never ran. An
        alert calling that a quality failure sends someone to audit the parser for a problem
        that is not there.
        """
        self._patch_run(monkeypatch, SilverDatasetEmpty("no parquet under silver/sorteos/"))

        with pytest.raises(SilverDataQualityFailed) as exc:
            main(["script.py", "--PARTITIONED_BUCKET", BUCKET])

        message = str(exc.value)
        assert "wiring problem" in message
        assert BUCKET in message

    def test_an_empty_report_does_not_pass_the_gate(self, monkeypatch):
        """``DQReport.success`` is False for zero suites; the gate must honour that.

        Validating nothing is the failure mode where a gate looks green forever.
        """
        self._patch_run(monkeypatch, DQReport(suites=[]))

        with pytest.raises(SilverDataQualityFailed):
            main(["script.py", "--PARTITIONED_BUCKET", BUCKET])


class TestArgumentsReachTheRunner:
    def test_the_bucket_argument_is_what_gets_validated(self, monkeypatch):
        seen = {}

        def fake_run_dq(bucket, silver_prefix):
            seen.update(bucket=bucket, silver_prefix=silver_prefix)
            return DQReport(suites=[outcome("s", passing())])

        monkeypatch.setattr("loteria.dq.runner.run_dq", fake_run_dq)
        main(["script.py", "--PARTITIONED_BUCKET", BUCKET])

        assert seen["bucket"] == BUCKET
        assert seen["silver_prefix"] == "silver/"

    def test_a_custom_silver_prefix_is_honoured(self, monkeypatch):
        seen = {}

        def fake_run_dq(bucket, silver_prefix):
            seen.update(silver_prefix=silver_prefix)
            return DQReport(suites=[outcome("s", passing())])

        monkeypatch.setattr("loteria.dq.runner.run_dq", fake_run_dq)
        main(["script.py", "--PARTITIONED_BUCKET", BUCKET, "--SILVER_PREFIX", "silver_v2/"])

        assert seen["silver_prefix"] == "silver_v2/"

    def test_the_correlation_id_reaches_the_environment(self, monkeypatch):
        """PR-018: the DQ verdict has to be stitchable to the logs it is judging."""
        monkeypatch.delenv("CORRELATION_ID", raising=False)
        monkeypatch.setattr(
            "loteria.dq.runner.run_dq",
            lambda bucket, silver_prefix: DQReport(suites=[outcome("s", passing())]),
        )

        main(["script.py", "--PARTITIONED_BUCKET", BUCKET, "--CORRELATION_ID", "exec-abc"])

        import os

        assert os.environ["CORRELATION_ID"] == "exec-abc"

    def test_a_real_environment_variable_still_wins(self, monkeypatch):
        """``setdefault``, not assignment — so an operator override is not clobbered."""
        monkeypatch.setenv("CORRELATION_ID", "set-by-hand")
        monkeypatch.setattr(
            "loteria.dq.runner.run_dq",
            lambda bucket, silver_prefix: DQReport(suites=[outcome("s", passing())]),
        )

        main(["script.py", "--PARTITIONED_BUCKET", BUCKET, "--CORRELATION_ID", "exec-abc"])

        import os

        assert os.environ["CORRELATION_ID"] == "set-by-hand"


# ==========================================================================================
# The alert text itself
# ==========================================================================================
class TestSummarizeFailures:
    def test_names_every_failure_when_there_are_few(self):
        report = DQReport(
            suites=[
                outcome("silver_sorteos", failing("expect_a", "fecha_sorteo")),
                outcome("silver_premios", failing("expect_b", "monto")),
            ]
        )
        summary = summarize_failures(report)

        assert "silver_sorteos.fecha_sorteo: expect_a" in summary
        assert "silver_premios.monto: expect_b" in summary
        assert summary.startswith("2 expectation(s) failed")

    def test_caps_the_list_and_says_how_many_are_hidden(self):
        """SNS bodies are read on a phone. Past a handful the useful fact is "a lot broke"."""
        failures = [failing(f"expect_{i}") for i in range(MAX_SUMMARIZED_FAILURES + 2)]
        report = DQReport(suites=[outcome("silver_premios", *failures)])

        summary = summarize_failures(report)

        assert f"{len(failures)} expectation(s) failed" in summary
        assert "and 2 more" in summary
        assert f"expect_{len(failures) - 1}" not in summary

    def test_includes_the_unexpected_row_count_when_gx_reports_one(self):
        report = DQReport(suites=[outcome("silver_premios", failing(count=4))])
        assert "[4 rows]" in summarize_failures(report)

    def test_survives_an_expectation_with_no_row_count(self):
        """Table-level expectations (row count, column set) report no unexpected count."""
        report = DQReport(
            suites=[outcome("silver_sorteos", failing("expect_table_row_count", "", None))]
        )
        summary = summarize_failures(report)

        assert "expect_table_row_count" in summary
        assert "rows]" not in summary

    def test_an_empty_report_is_described_honestly(self):
        """``DQReport.success`` is False here, but nothing "failed".

        Saying "0 expectations failed" would be a lie in the more alarming direction — it
        reads as a green run that somehow failed.
        """
        summary = summarize_failures(DQReport(suites=[]))
        assert "covered no suites" in summary


class TestFormatReport:
    def test_moved_to_the_library_so_the_cli_and_the_job_agree(self):
        """PR-033 moved this out of scripts/run_dq.py. Two formatters would drift, and the
        SNS alert would stop matching the log it tells you to go read."""
        from loteria.dq import runner

        assert hasattr(runner, "format_report")

    def test_renders_a_pass_without_listing_expectations(self):
        report = DQReport(suites=[outcome("silver_sorteos", passing(), passing())])
        text = format_report(report)

        assert "[PASS] silver_sorteos: 2 expectations, 10 rows from 2 files" in text
        assert "DQ RESULT: PASS" in text
        assert "FAILED" not in text

    def test_lists_each_failure_under_its_suite(self):
        report = DQReport(suites=[outcome("silver_premios", passing(), failing())])
        text = format_report(report)

        assert "[FAIL] silver_premios" in text
        assert "FAILED expect_column_values_to_be_unique on 'numero_sorteo'" in text
        assert "4 unexpected (3.50%)" in text
        assert "DQ RESULT: FAIL" in text

    def test_carries_no_ansi_escapes(self):
        """This is read out of a CloudWatch log and an SNS body, where colour is noise."""
        report = DQReport(suites=[outcome("silver_premios", failing())])
        assert "\x1b[" not in format_report(report)


class TestTheVerdictReachesThePerJobLogGroup:
    """PR-033.1.

    PR-033 pointed the runbook at `/aws-glue/jobs/loteria-silver-dq-prod` for the verdict.
    The first real run (2026-09-16) left that group with ZERO streams — continuous logging
    ships Spark's log4j output and this job never starts Spark — so the verdict was only
    ever in the account-wide group. The entry point now writes to the group itself, and
    these tests pin the two halves of that: it is wired when Glue supplies the group, and it
    stays out of the way when nothing does.
    """

    class CollectingHandler(logging.Handler):
        def __init__(self):
            super().__init__()
            self.messages: list[str] = []

        def emit(self, record):
            self.messages.append(record.getMessage())

    def _patch(self, monkeypatch, report):
        monkeypatch.setattr("loteria.dq.runner.run_dq", lambda bucket, silver_prefix: report)
        seen = {}
        handler = self.CollectingHandler()

        def fake_attach(log_group, log_stream, **kwargs):
            seen["group"] = log_group
            seen["stream"] = log_stream
            return handler if log_group else None

        monkeypatch.setattr(
            "loteria.common.cloudwatch_logging.attach_cloudwatch_handler", fake_attach
        )
        return seen, handler

    def test_the_group_terraform_passes_is_the_group_used(self, monkeypatch):
        seen, _ = self._patch(monkeypatch, DQReport(suites=[outcome("s", passing())]))
        monkeypatch.setenv("CORRELATION_ID", "exec-42")

        main(["script.py", "--PARTITIONED_BUCKET", BUCKET, "--DQ_LOG_GROUP", "/aws-glue/x"])

        assert seen["group"] == "/aws-glue/x"
        # The stream is the correlation id, so a stream ties back to the pipeline run that
        # produced it — the whole point of PR-018's id.
        assert seen["stream"] == "exec-42"

    def test_the_verdict_lands_in_the_group_exactly_once(self, monkeypatch, capsys):
        _, handler = self._patch(monkeypatch, DQReport(suites=[outcome("s", passing())]))

        main(["script.py", "--PARTITIONED_BUCKET", BUCKET, "--DQ_LOG_GROUP", "/aws-glue/x"])

        assert len(handler.messages) == 1
        assert "DQ RESULT: PASS" in handler.messages[0]
        # And exactly once on stdout too: the verdict is printed for the driver log and
        # routed to the group, never logged through the root logger, which would put a
        # JSON-escaped second copy on stdout.
        assert capsys.readouterr().out.count("DQ RESULT: PASS") == 1

    def test_a_failing_verdict_still_reaches_the_group_before_raising(self, monkeypatch):
        report = DQReport(suites=[outcome("silver_premios", passing(), failing())])
        _, handler = self._patch(monkeypatch, report)

        with pytest.raises(SilverDataQualityFailed):
            main(["script.py", "--PARTITIONED_BUCKET", BUCKET, "--DQ_LOG_GROUP", "/aws-glue/x"])

        # The failing run is the one somebody is woken up for. If the verdict only shipped
        # on the success path, the group would be empty exactly when it is needed.
        assert handler.messages and "FAIL" in handler.messages[0].upper()

    def test_without_the_argument_nothing_is_attached_and_the_gate_still_works(
        self, monkeypatch, capsys
    ):
        seen, handler = self._patch(monkeypatch, DQReport(suites=[outcome("s", passing())]))

        main(["script.py", "--PARTITIONED_BUCKET", BUCKET])

        assert seen["group"] is None
        assert handler.messages == []
        assert "DQ RESULT: PASS" in capsys.readouterr().out
