"""Tests for the Glue entry point of the Silver DQ job (PR-033).

The validation itself is PR-032's territory (``test_dq_suites.py`` / ``test_dq_runner.py``).
What is tested here is the seam between Glue and that library, which is where this job can
fail in ways nothing else would notice:

* an optional job argument that ``getResolvedOptions`` would have refused;
* the exception message, which is not a nicety — Step Functions puts Glue's ``ErrorMessage``
  straight into the SNS alert, so this string *is* the email the owner reads;
* the distinction between "the data is bad" and "there is no data".

``awsglue`` cannot be installed outside the Glue runtime; ``tests/conftest.py`` registers the
stub that makes the module importable (PR-030).
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

from loteria.dq.runner import DQReport, ExpectationOutcome, SuiteOutcome

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
glue_dq_main = importlib.import_module("glue_dq_main")


# ==========================================================================================
# Helpers
# ==========================================================================================
def failing_report(*failures: tuple[str, str, str, int | None]) -> DQReport:
    """Build a report whose failures are exactly the (suite, expectation, column, n) given."""
    by_suite: dict[str, list[ExpectationOutcome]] = {}
    for suite, expectation, column, count in failures:
        by_suite.setdefault(suite, []).append(
            ExpectationOutcome(expectation, column, False, count, 1.0)
        )

    return DQReport(
        suites=[
            SuiteOutcome(suite=name, dataset=name, rows=10, files=1, results=results)
            for name, results in by_suite.items()
        ]
    )


def passing_report() -> DQReport:
    return DQReport(
        suites=[
            SuiteOutcome(
                suite="silver_sorteos",
                dataset="sorteos",
                rows=111,
                files=111,
                results=[
                    ExpectationOutcome("expect_column_values_to_be_unique", "n", True, 0, 0.0)
                ],
            )
        ]
    )


@pytest.fixture
def glue_args(monkeypatch):
    """Stand in for Glue's argument resolution and pin the argv the job sees."""

    def _install(argv: list[str], resolved: dict[str, str] | None = None):
        monkeypatch.setattr(
            glue_dq_main,
            "getResolvedOptions",
            lambda _argv, _names: resolved or {"PARTITIONED_BUCKET": "test-bucket"},
        )
        monkeypatch.setattr(sys, "argv", argv)
        return argv

    return _install


@pytest.fixture
def captured_run_dq(monkeypatch):
    """Replace run_dq with a recorder that returns whatever the test wants."""
    calls = {}

    def _install(result):
        def fake(**kwargs):
            calls.update(kwargs)
            if isinstance(result, Exception):
                raise result
            return result

        monkeypatch.setattr(glue_dq_main, "run_dq", fake)
        return calls

    return _install


# ==========================================================================================
# Argument handling
# ==========================================================================================
class TestOptionalArguments:
    """``getResolvedOptions`` raises for any name it was told to expect but did not receive,
    so genuinely optional arguments cannot go through it."""

    def test_reads_the_space_separated_form(self):
        found = glue_dq_main._optional_args(["job.py", "--SILVER_PREFIX", "otro/"])
        assert found == {"SILVER_PREFIX": "otro/"}

    def test_reads_the_equals_form(self):
        found = glue_dq_main._optional_args(["job.py", "--CORRELATION_ID=abc-123"])
        assert found == {"CORRELATION_ID": "abc-123"}

    def test_absent_arguments_are_simply_absent(self):
        assert glue_dq_main._optional_args(["job.py"]) == {}

    def test_a_trailing_flag_with_no_value_is_ignored(self):
        """Guards against an IndexError on a malformed argument list."""
        assert glue_dq_main._optional_args(["job.py", "--SILVER_PREFIX"]) == {}

    def test_unrelated_arguments_are_not_picked_up(self):
        """Glue passes a pile of its own --job-language / --enable-* arguments."""
        argv = ["job.py", "--job-language", "python", "--enable-spark-ui", "false"]
        assert glue_dq_main._optional_args(argv) == {}


class TestMainWiring:
    def test_passes_the_bucket_through_to_run_dq(self, glue_args, captured_run_dq):
        glue_args(["job.py"])
        calls = captured_run_dq(passing_report())

        glue_dq_main.main()

        assert calls["bucket"] == "test-bucket"

    def test_defaults_the_silver_prefix(self, glue_args, captured_run_dq):
        glue_args(["job.py"])
        calls = captured_run_dq(passing_report())

        glue_dq_main.main()

        assert calls["silver_prefix"] == "silver/"

    def test_an_explicit_silver_prefix_wins(self, glue_args, captured_run_dq):
        glue_args(["job.py", "--SILVER_PREFIX", "otro/"])
        calls = captured_run_dq(passing_report())

        glue_dq_main.main()

        assert calls["silver_prefix"] == "otro/"

    def test_correlation_id_reaches_the_environment(self, glue_args, captured_run_dq, monkeypatch):
        """PR-018: configure_logging reads CORRELATION_ID from the environment, but Glue
        delivers job arguments on the command line — so something has to bridge them, or the
        DQ verdict cannot be stitched to the run it is judging."""
        monkeypatch.delenv("CORRELATION_ID", raising=False)
        glue_args(["job.py", "--CORRELATION_ID", "exec-42"])
        captured_run_dq(passing_report())

        glue_dq_main.main()

        import os

        assert os.environ["CORRELATION_ID"] == "exec-42"


# ==========================================================================================
# Failing is the job
# ==========================================================================================
class TestFailureBehaviour:
    def test_a_clean_report_returns_without_raising(self, glue_args, captured_run_dq):
        """Glue marks the run FAILED on any uncaught exception, so a pass must be silent."""
        glue_args(["job.py"])
        captured_run_dq(passing_report())

        assert glue_dq_main.main() is None

    def test_a_failed_expectation_raises(self, glue_args, captured_run_dq):
        """The raise is what fails the Glue run, which is what fails the `.sync` Step
        Functions task, which is what stops Gold. Returning quietly here would let the
        pipeline build Gold from data the gate just rejected."""
        glue_args(["job.py"])
        captured_run_dq(
            failing_report(
                ("silver_premios", "expect_column_values_to_be_in_set", "departamento", 12)
            )
        )

        with pytest.raises(glue_dq_main.SilverDataQualityFailed):
            glue_dq_main.main()

    def test_the_message_names_the_suite_expectation_and_column(self, glue_args, captured_run_dq):
        """This string is Glue's ErrorMessage, which Step Functions puts verbatim into the
        SNS alert. "DQ failed" alone would send the reader to the console to find out what
        broke."""
        glue_args(["job.py"])
        captured_run_dq(
            failing_report(
                ("silver_premios", "expect_column_values_to_be_in_set", "departamento", 12)
            )
        )

        with pytest.raises(glue_dq_main.SilverDataQualityFailed) as excinfo:
            glue_dq_main.main()

        message = str(excinfo.value)
        assert "silver_premios" in message
        assert "expect_column_values_to_be_in_set" in message
        assert "departamento" in message

    def test_the_message_says_gold_was_not_built(self, glue_args, captured_run_dq):
        """The reader's first question is whether the gold tables are now wrong. They are
        not — they are stale, because the gate stopped the rebuild."""
        glue_args(["job.py"])
        captured_run_dq(
            failing_report(("silver_sorteos", "expect_column_values_to_be_unique", "n", 2))
        )

        with pytest.raises(glue_dq_main.SilverDataQualityFailed) as excinfo:
            glue_dq_main.main()

        assert "Gold was NOT built" in str(excinfo.value)

    def test_missing_silver_is_reported_as_a_different_problem(self, glue_args, captured_run_dq):
        """An empty prefix means the wrong bucket or a transformer that never ran. Describing
        that as bad data would send the reader to inspect Parquet that does not exist."""
        from loteria.dq.runner import SilverDatasetEmpty

        glue_args(["job.py"])
        captured_run_dq(SilverDatasetEmpty("No Parquet files under s3://b/silver/sorteos/"))

        with pytest.raises(
            glue_dq_main.SilverDataQualityFailed, match="No Silver data to validate"
        ):
            glue_dq_main.main()

    def test_the_full_report_is_printed_for_the_log(self, glue_args, captured_run_dq, capsys):
        """The exception carries a one-line summary; the Glue log gets the whole thing."""
        glue_args(["job.py"])
        captured_run_dq(
            failing_report(("silver_sorteos", "expect_column_values_to_be_unique", "n", 2))
        )

        with pytest.raises(glue_dq_main.SilverDataQualityFailed):
            glue_dq_main.main()

        out = capsys.readouterr().out
        assert "[FAIL] silver_sorteos" in out
        assert "DQ RESULT: FAIL" in out
