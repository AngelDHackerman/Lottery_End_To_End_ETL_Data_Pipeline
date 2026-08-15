"""Tests for the DQ runner and its CLI (PR-032).

Everything here runs against moto's in-process S3, so the Silver layout — Hive partitions,
one Parquet file per draw, two datasets side by side — is exercised for real rather than
mocked away.

The centrepiece is ``TestAgainstRealTransformerOutput``: it runs the actual transformer over
the actual anonymized sorteo fixtures and validates whatever it writes. That is the only
test here that can catch the suites and the pipeline drifting apart. Everything else builds
frames by hand and would keep passing even if the transformer started emitting a different
schema tomorrow.
"""

from __future__ import annotations

import importlib
import io
import sys
from pathlib import Path

import boto3
import pandas as pd
import pytest
from moto import mock_aws

from loteria.dq.runner import (
    DATASET_SUITES,
    DQReport,
    ExpectationOutcome,
    SilverDatasetEmpty,
    SuiteOutcome,
    list_parquet_keys,
    load_silver_dataset,
    run_dq,
)

REGION = "us-east-1"
PARTITIONED = "test-partitioned-bucket"
SIMPLE = "test-simple-bucket"
RAW_PREFIX = "raw/"
SIMPLE_PREFIX = "processed/"
SILVER_PREFIX = "silver/"

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "sorteos"

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
run_dq_cli = importlib.import_module("run_dq")


# ==========================================================================================
# Fixtures
# ==========================================================================================
@pytest.fixture
def s3():
    with mock_aws():
        client = boto3.client("s3", region_name=REGION)
        client.create_bucket(Bucket=PARTITIONED)
        client.create_bucket(Bucket=SIMPLE)
        yield client


@pytest.fixture
def transformer(monkeypatch):
    """The real transformer, with its import-time Secrets Manager call neutralised.

    Same approach as PR-030's ``tests/unit/test_transformer.py``; see that module for why
    the module has to be evicted from ``sys.modules`` first.
    """
    import loteria.common.aws_secrets as aws_secrets

    monkeypatch.setattr(
        aws_secrets, "get_secrets", lambda: {"partitioned": PARTITIONED, "simple": SIMPLE}
    )
    sys.modules.pop("loteria.transformer.transformer", None)

    module = importlib.import_module("loteria.transformer.transformer")
    monkeypatch.setattr(module, "partitioned_bucket", PARTITIONED)
    monkeypatch.setattr(module, "simple_bucket", SIMPLE)

    yield module

    sys.modules.pop("loteria.transformer.transformer", None)


def put_silver(s3, dataset: str, df: pd.DataFrame, *, year: int, sorteo: int) -> str:
    """Write one Parquet file where the transformer would have written it."""
    buffer = io.BytesIO()
    df.to_parquet(buffer, index=False)
    key = f"{SILVER_PREFIX}{dataset}/year={year}/sorteo={sorteo}/{dataset}.parquet"
    s3.put_object(Bucket=PARTITIONED, Key=key, Body=buffer.getvalue())
    return key


def sorteos_frame(numero: int = 3046, **overrides) -> pd.DataFrame:
    data = {
        "numero_sorteo": pd.Series([numero], dtype="int64"),
        "tipo_sorteo": pd.Series(["ORDINARIO"], dtype="string"),
        "fecha_sorteo": pd.to_datetime(["2024-06-01"]),
        "fecha_caducidad": pd.to_datetime(["2024-08-30"]),
        "primer_premio": pd.Series([12345], dtype="Int64"),
        "segundo_premio": pd.Series([2222], dtype="Int64"),
        "tercer_premio": pd.Series([4444], dtype="Int64"),
        "reintegro_primer_premio": pd.Series([5], dtype="Int64"),
        "reintegro_segundo_premio": pd.Series([2], dtype="Int64"),
        "reintegro_tercer_premio": pd.Series([4], dtype="Int64"),
    }
    data.update(overrides)
    return pd.DataFrame(data)


def premios_frame(numero: int = 3046, **overrides) -> pd.DataFrame:
    data = {
        "numero_sorteo": pd.Series([numero, numero], dtype="int64"),
        "numero_premiado": pd.Series([1234, 5678], dtype="Int64"),
        "letras": pd.Series(["P", "TT"], dtype="string"),
        "monto": pd.Series([1000.0, 500.0], dtype="float64"),
        "vendedor": pd.Series(["UN VENDEDOR", "NO VENDIDO"], dtype="string"),
        "ciudad": pd.Series(["ANTIGUA", None], dtype="string"),
        "departamento": pd.Series(["SACATEPÉQUEZ", None], dtype="string"),
    }
    data.update(overrides)
    return pd.DataFrame(data)


def seed_valid_silver(s3, sorteos=(3046, 3047)):
    for numero in sorteos:
        put_silver(s3, "sorteos", sorteos_frame(numero), year=2024, sorteo=numero)
        put_silver(s3, "premios", premios_frame(numero), year=2024, sorteo=numero)


# ==========================================================================================
# Listing and loading
# ==========================================================================================
class TestListing:
    def test_finds_parquet_across_every_partition(self, s3):
        seed_valid_silver(s3)
        keys = list_parquet_keys(PARTITIONED, f"{SILVER_PREFIX}sorteos/")

        assert len(keys) == 2
        assert all(k.endswith(".parquet") for k in keys)

    def test_ignores_non_parquet_objects(self, s3):
        """Athena and the crawlers leave ``_SUCCESS`` markers and metadata files around."""
        seed_valid_silver(s3, sorteos=(3046,))
        s3.put_object(Bucket=PARTITIONED, Key=f"{SILVER_PREFIX}sorteos/_SUCCESS", Body=b"")
        s3.put_object(
            Bucket=PARTITIONED, Key=f"{SILVER_PREFIX}sorteos/notes.txt", Body=b"ignore me"
        )

        assert list_parquet_keys(PARTITIONED, f"{SILVER_PREFIX}sorteos/") == [
            f"{SILVER_PREFIX}sorteos/year=2024/sorteo=3046/sorteos.parquet"
        ]

    def test_does_not_leak_across_datasets(self, s3):
        """``silver/sorteos/`` and ``silver/premios/`` share a parent prefix; a listing
        rooted one level too high would concatenate two different schemas."""
        seed_valid_silver(s3)

        assert all("premios" not in k for k in list_parquet_keys(PARTITIONED, "silver/sorteos/"))
        assert all("sorteos" not in k for k in list_parquet_keys(PARTITIONED, "silver/premios/"))

    def test_returns_keys_sorted(self, s3):
        seed_valid_silver(s3, sorteos=(3047, 3046, 3048))
        keys = list_parquet_keys(PARTITIONED, f"{SILVER_PREFIX}sorteos/")

        assert keys == sorted(keys)


class TestLoading:
    def test_concatenates_every_partition_into_one_frame(self, s3):
        seed_valid_silver(s3)
        df, keys = load_silver_dataset(PARTITIONED, "sorteos")

        assert len(keys) == 2
        assert len(df) == 2
        assert sorted(df["numero_sorteo"]) == [3046, 3047]

    def test_index_is_reset_so_rows_are_addressable(self, s3):
        """A naive concat keeps each file's 0-based index, which makes every per-row report
        ambiguous once there is more than one file."""
        seed_valid_silver(s3)
        df, _ = load_silver_dataset(PARTITIONED, "premios")

        assert list(df.index) == list(range(len(df)))

    def test_empty_prefix_raises_its_own_error(self, s3):
        """Not a DQ failure — "there is no data" needs a different response from
        "the data is wrong"."""
        with pytest.raises(SilverDatasetEmpty, match="No Parquet files"):
            load_silver_dataset(PARTITIONED, "sorteos")

    def test_the_error_names_the_uri_that_was_searched(self, s3):
        """The realistic cause is a wrong bucket or prefix, so the message has to say which
        one was used."""
        with pytest.raises(SilverDatasetEmpty) as excinfo:
            load_silver_dataset(PARTITIONED, "premios")

        assert f"s3://{PARTITIONED}/{SILVER_PREFIX}premios/" in str(excinfo.value)

    def test_honours_a_custom_silver_prefix(self, s3):
        buffer = io.BytesIO()
        sorteos_frame().to_parquet(buffer, index=False)
        s3.put_object(
            Bucket=PARTITIONED,
            Key="otro/sorteos/year=2024/sorteo=3046/sorteos.parquet",
            Body=buffer.getvalue(),
        )

        df, _ = load_silver_dataset(PARTITIONED, "sorteos", silver_prefix="otro/")
        assert len(df) == 1


# ==========================================================================================
# run_dq
# ==========================================================================================
class TestRunDQ:
    def test_clean_silver_passes_both_suites(self, s3):
        seed_valid_silver(s3)
        report = run_dq(PARTITIONED)

        assert report.success
        assert {s.suite for s in report.suites} == set(DATASET_SUITES.values())

    def test_reports_row_and_file_counts(self, s3):
        seed_valid_silver(s3)
        report = run_dq(PARTITIONED)
        premios = next(s for s in report.suites if s.dataset == "premios")

        assert premios.files == 2
        assert premios.rows == 4

    def test_a_duplicated_sorteo_across_two_files_fails(self, s3):
        """The cross-file failure. Each file is individually valid — only the concatenation
        is wrong, which is exactly what a per-file GX batch would miss."""
        put_silver(s3, "sorteos", sorteos_frame(3046), year=2024, sorteo=3046)
        put_silver(s3, "sorteos", sorteos_frame(3046), year=2024, sorteo=9999)
        put_silver(s3, "premios", premios_frame(3046), year=2024, sorteo=3046)

        report = run_dq(PARTITIONED)

        assert not report.success
        sorteos = next(s for s in report.suites if s.dataset == "sorteos")
        assert any(f.expectation == "expect_column_values_to_be_unique" for f in sorteos.failures)

    def test_a_bad_premio_does_not_mask_the_sorteos_result(self, s3):
        """Both suites run even after one fails, so a single execution reports everything
        that is wrong instead of one thing at a time."""
        seed_valid_silver(s3, sorteos=(3046,))
        put_silver(
            s3,
            "premios",
            premios_frame(3047, monto=pd.Series([-5.0, 500.0], dtype="float64")),
            year=2024,
            sorteo=3047,
        )

        report = run_dq(PARTITIONED)

        assert not report.success
        assert len(report.suites) == 2
        assert next(s for s in report.suites if s.dataset == "sorteos").success

    def test_can_validate_a_single_dataset(self, s3):
        seed_valid_silver(s3, sorteos=(3046,))
        report = run_dq(PARTITIONED, datasets=["sorteos"])

        assert [s.dataset for s in report.suites] == ["sorteos"]

    def test_an_unknown_dataset_is_rejected_before_any_s3_call(self, s3):
        with pytest.raises(ValueError, match="Unknown dataset"):
            run_dq(PARTITIONED, datasets=["gold"])

    def test_missing_silver_raises_rather_than_reporting_failure(self, s3):
        with pytest.raises(SilverDatasetEmpty):
            run_dq(PARTITIONED)


class TestDQReport:
    def test_an_empty_report_is_not_a_success(self):
        """``all([])`` is True. Validating nothing must not look like validating cleanly."""
        assert not DQReport(suites=[]).success

    def test_to_dict_is_json_serialisable(self, s3):
        import json

        seed_valid_silver(s3, sorteos=(3046,))
        report = run_dq(PARTITIONED)

        payload = json.loads(json.dumps(report.to_dict(), ensure_ascii=False))
        assert payload["success"] is True
        assert len(payload["suites"]) == 2

    def test_one_failed_expectation_fails_the_whole_suite(self):
        outcome = SuiteOutcome(
            suite="s",
            dataset="d",
            rows=1,
            files=1,
            results=[
                ExpectationOutcome("a", "col", True, 0, 0.0),
                ExpectationOutcome("b", "col", False, 3, 1.5),
            ],
        )

        assert not outcome.success
        assert [f.expectation for f in outcome.failures] == ["b"]

    def test_a_report_fails_if_any_suite_fails(self):
        passing = SuiteOutcome(
            suite="p",
            dataset="d",
            rows=1,
            files=1,
            results=[ExpectationOutcome("a", "col", True, 0, 0.0)],
        )
        failing = SuiteOutcome(
            suite="f",
            dataset="e",
            rows=1,
            files=1,
            results=[ExpectationOutcome("b", "col", False, 1, 100.0)],
        )

        assert DQReport(suites=[passing]).success
        assert not DQReport(suites=[passing, failing]).success


# ==========================================================================================
# The real thing: transformer output validated by the suites
# ==========================================================================================
class TestAgainstRealTransformerOutput:
    """Run the pipeline for real, then validate what it produced.

    This is the test that fails when the transformer and the suites drift apart — a column
    rename, a dtype change, a new departamento spelling. The hand-built frames elsewhere in
    this module encode what we *believe* Silver looks like; this one uses what it *is*.
    """

    @pytest.fixture
    def silver_from_fixtures(self, s3, transformer):
        for name, sorteo, year in [
            ("ordinario_3046.txt", 3046, 2024),
            ("ordinario_3132.txt", 3132, 2025),
            ("extraordinario_413.txt", 413, 2026),
        ]:
            s3.put_object(
                Bucket=PARTITIONED,
                Key=f"{RAW_PREFIX}year={year}/sorteo={sorteo}/results_raw_no._{sorteo}.txt",
                Body=(FIXTURES / name).read_text(encoding="utf-8").encode("utf-8"),
            )

        transformer.transform(
            bucket_name=PARTITIONED,
            raw_prefix=RAW_PREFIX,
            simple_prefix=SIMPLE_PREFIX,
            silver_prefix=SILVER_PREFIX,
        )
        return s3

    def test_the_suites_pass_on_what_the_transformer_actually_writes(self, silver_from_fixtures):
        report = run_dq(PARTITIONED)

        failures = [(s.suite, f.expectation, f.column) for s in report.suites for f in s.failures]
        assert report.success, failures

    def test_all_three_fixture_draws_are_covered(self, silver_from_fixtures):
        """Guards the fixture above: if `transform` silently skipped a file, the suites would
        pass on a smaller dataset and this test would still read as green."""
        report = run_dq(PARTITIONED)
        sorteos = next(s for s in report.suites if s.dataset == "sorteos")

        assert sorteos.rows == 3
        assert sorteos.files == 3

    def test_real_departamentos_are_all_in_the_expected_set(self, silver_from_fixtures):
        """The suite's value set was derived from prod. This proves the fixtures agree with
        it, so the set cannot be trimmed to whatever prod happened to contain that day."""
        df, _ = load_silver_dataset(PARTITIONED, "premios")
        report = run_dq(PARTITIONED, datasets=["premios"])

        assert df["departamento"].notna().any(), "fixture has no geography to check"
        assert report.success


# ==========================================================================================
# CLI
# ==========================================================================================
class TestCLI:
    def test_exits_zero_on_clean_data(self, s3, capsys):
        seed_valid_silver(s3)

        assert run_dq_cli.main(["--bucket", PARTITIONED]) == run_dq_cli.EXIT_OK
        assert "DQ RESULT: PASS" in capsys.readouterr().out

    def test_exits_non_zero_on_a_dq_failure(self, s3, capsys):
        """The exit code is the contract PR-033 depends on to stop the Gold build."""
        seed_valid_silver(s3, sorteos=(3046,))
        put_silver(
            s3,
            "premios",
            premios_frame(3047, letras=pd.Series(["p", "tt"], dtype="string")),
            year=2024,
            sorteo=3047,
        )

        assert run_dq_cli.main(["--bucket", PARTITIONED]) == run_dq_cli.EXIT_DQ_FAILED
        assert "DQ RESULT: FAIL" in capsys.readouterr().out

    def test_missing_data_gets_its_own_exit_code(self, s3, capsys):
        assert run_dq_cli.main(["--bucket", PARTITIONED]) == run_dq_cli.EXIT_NO_DATA
        assert "NO DATA" in capsys.readouterr().err

    def test_missing_bucket_is_a_usage_error(self, s3, monkeypatch, capsys):
        monkeypatch.delenv("PARTITIONED_BUCKET", raising=False)
        # The default was captured at parser-build time from the environment, so rebuild it.
        importlib.reload(run_dq_cli)

        assert run_dq_cli.main([]) == run_dq_cli.EXIT_USAGE
        assert "--bucket is required" in capsys.readouterr().err

    def test_the_failure_report_names_the_expectation_and_the_column(self, s3, capsys):
        """This text is what lands in the SNS alert body in PR-033. "DQ failed" alone would
        send someone to the console to find out what broke."""
        seed_valid_silver(s3, sorteos=(3046,))
        put_silver(
            s3,
            "premios",
            premios_frame(3047, monto=pd.Series([-5.0, 500.0], dtype="float64")),
            year=2024,
            sorteo=3047,
        )

        run_dq_cli.main(["--bucket", PARTITIONED])
        out = capsys.readouterr().out

        assert "expect_column_values_to_be_between" in out
        assert "monto" in out

    def test_writes_a_json_report_when_asked(self, s3, tmp_path):
        seed_valid_silver(s3, sorteos=(3046,))
        destination = tmp_path / "nested" / "dq.json"

        run_dq_cli.main(["--bucket", PARTITIONED, "--json-report", str(destination)])

        import json

        payload = json.loads(destination.read_text(encoding="utf-8"))
        assert payload["success"] is True

    def test_sync_suites_is_idempotent(self, tmp_path):
        """Re-running the sync must not produce a diff. GX mints fresh UUIDs on every write,
        so without normalisation a one-line change would rewrite the whole file."""
        context_dir = tmp_path / "great_expectations"

        run_dq_cli.sync_suites(context_dir)
        first = {
            p.name: p.read_text(encoding="utf-8")
            for p in (context_dir / "expectations").glob("*.json")
        }

        run_dq_cli.sync_suites(context_dir)
        second = {
            p.name: p.read_text(encoding="utf-8")
            for p in (context_dir / "expectations").glob("*.json")
        }

        assert first == second
        assert set(first) == {f"{name}.json" for name in DATASET_SUITES.values()}
