"""Unit tests for ``loteria.transformer.transformer`` against fake S3 (PR-030).

These run the **real** transformer end to end — parse, schema enforcement, Parquet write,
upload — with moto standing in for S3. Nothing about the transform is mocked; the only fake
is AWS.

Two things have to be defused before the module can even be imported, and both are worth
understanding because they are properties of how this code runs in Glue:

1. ``from awsglue.utils import getResolvedOptions`` at module scope. ``awsglue`` ships only
   inside the Glue runtime, so a plain import fails anywhere else. Stubbed in
   ``tests/conftest.py``.
2. ``buckets = get_secrets()`` at module scope — a Secrets Manager call that fires on
   **import**, not on use. (Same fact that forced ``scripts/glue_zip_main.py`` to bridge
   ``--LOTERIA_SECRET_NAME`` into the environment before importing the transformer.) Patched
   below before the first import.

``mock_aws``, not ``mock_s3``: the latter is the moto v4 API and was removed in moto 5.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pandas as pd
import pytest

boto3 = pytest.importorskip("boto3")
from moto import mock_aws  # noqa: E402

REGION = "us-east-1"
PARTITIONED = "test-partitioned-bucket"
RAW_PREFIX = "raw/"
SILVER_PREFIX = "silver/"

# PR-041.2 deleted the transformer's second write target. The bucket is still created by
# the `s3` fixture below and is still named here, because "writes to exactly one bucket" is
# only checkable against a second bucket that exists and stays empty. A test that just
# asserted the Silver keys would pass identically whether or not the flat copies came back.
OTHER_BUCKET = "test-simple-bucket"
OTHER_BUCKET_PREFIX = "processed/"

FIXTURES = Path(__file__).parents[1] / "fixtures" / "sorteos"

# The canonical Silver schemas. Hard-coded rather than derived, because "the schema is
# whatever the code produces" is not a test — these are the columns Athena, the crawlers and
# the 7 gold CTAS all depend on.
PREMIOS_COLUMNS = [
    "numero_sorteo",
    "numero_premiado",
    "letras",
    "monto",
    "vendedor",
    "ciudad",
    "departamento",
]
SORTEOS_COLUMNS = [
    "numero_sorteo",
    "tipo_sorteo",
    "fecha_sorteo",
    "fecha_caducidad",
    "primer_premio",
    "segundo_premio",
    "tercer_premio",
    "reintegro_primer_premio",
    "reintegro_segundo_premio",
    "reintegro_tercer_premio",
]

# Types are asserted at the PARQUET level, not the pandas level, because Parquet is the
# actual contract: the Glue crawler infers the Athena table from these files, and the 7 gold
# CTAS read that table. The pandas dtype is an implementation detail on the way there.
#
# It is also the only version-stable choice. Local pandas is 3.x; Glue Python Shell 3.9 ships
# a far older pandas, and the two disagree about what an un-cast string column is
# (`object` vs the new `str` dtype). Both still land as a Parquet string, which is what
# matters. For the same reason string columns are asserted with a predicate rather than an
# exact name — pyarrow may write `string` or `large_string` depending on version.
#
# Numeric and timestamp types ARE pinned exactly: the transformer casts them explicitly via
# _to_int64/_to_float64/to_datetime, so drift there would be a real regression, and int32 vs
# int64 is a difference Athena can see.
INT = "int64"
DOUBLE = "double"
TIMESTAMP = "timestamp[us]"
STRING = "<string>"  # sentinel: is_string or is_large_string

PREMIOS_PARQUET_TYPES = {
    "numero_sorteo": INT,
    "numero_premiado": INT,
    "letras": STRING,
    "monto": DOUBLE,
    "vendedor": STRING,
    "ciudad": STRING,
    "departamento": STRING,
}
SORTEOS_PARQUET_TYPES = {
    "numero_sorteo": INT,
    "tipo_sorteo": STRING,
    "fecha_sorteo": TIMESTAMP,
    "fecha_caducidad": TIMESTAMP,
    "primer_premio": INT,
    "segundo_premio": INT,
    "tercer_premio": INT,
    "reintegro_primer_premio": INT,
    "reintegro_segundo_premio": INT,
    "reintegro_tercer_premio": INT,
}


def assert_parquet_types(schema, expected: dict[str, str]) -> None:
    import pyarrow.types as pat

    for name, want in expected.items():
        field = schema.field(name)
        if want is STRING:
            assert pat.is_string(field.type) or pat.is_large_string(
                field.type
            ), f"{name}: {field.type} is not a Parquet string"
        else:
            assert str(field.type) == want, f"{name}: {field.type} != {want}"


# ==========================================================================================
# Fixtures
# ==========================================================================================
@pytest.fixture
def transformer(monkeypatch):
    """Import the transformer with its import-time AWS call neutralised.

    ``get_secrets`` is patched on ``loteria.common.aws_secrets`` *before* the transformer is
    imported, and the module is evicted from ``sys.modules`` first so a previous test's copy
    (carrying real module-level bucket names) cannot be reused.
    """
    import loteria.common.aws_secrets as aws_secrets

    monkeypatch.setattr(
        aws_secrets,
        "get_secrets",
        lambda: {"partitioned": PARTITIONED},
    )
    sys.modules.pop("loteria.transformer.transformer", None)

    mod = importlib.import_module("loteria.transformer.transformer")

    # transform() reads from its `bucket_name` argument but WRITES to these module globals.
    # Set them explicitly: a test that only passed bucket_name would silently write to
    # whatever the import-time secret returned.
    monkeypatch.setattr(mod, "partitioned_bucket", PARTITIONED)

    yield mod

    sys.modules.pop("loteria.transformer.transformer", None)


@pytest.fixture
def s3():
    """Both buckets, empty, in an in-process fake S3.

    The second one is only ever asserted to stay empty — see OTHER_BUCKET.
    """
    with mock_aws():
        client = boto3.client("s3", region_name=REGION)
        client.create_bucket(Bucket=PARTITIONED)
        client.create_bucket(Bucket=OTHER_BUCKET)
        yield client


def put_raw(s3, *, sorteo: int, year: int, fixture: str = "ordinario_3046.txt", body=None):
    """Place a raw .txt at raw/year=<year>/sorteo=<sorteo>/ and return its key."""
    key = f"{RAW_PREFIX}year={year}/sorteo={sorteo}/results_raw_no._{sorteo}.txt"
    content = body if body is not None else (FIXTURES / fixture).read_text(encoding="utf-8")
    s3.put_object(Bucket=PARTITIONED, Key=key, Body=content.encode("utf-8"))
    return key


def read_parquet(s3, bucket: str, key: str) -> pd.DataFrame:
    import io

    body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    return pd.read_parquet(io.BytesIO(body))


def read_schema(s3, bucket: str, key: str):
    """The Parquet schema as written — what the Glue crawler will read."""
    import io

    import pyarrow.parquet as pq

    body = s3.get_object(Bucket=bucket, Key=key)["Body"].read()
    return pq.read_schema(io.BytesIO(body)).remove_metadata()


def keys_under(s3, bucket: str, prefix: str) -> list[str]:
    resp = s3.list_objects_v2(Bucket=bucket, Prefix=prefix)
    return sorted(o["Key"] for o in resp.get("Contents", []))


def run(transformer):
    transformer.transform(
        bucket_name=PARTITIONED,
        raw_prefix=RAW_PREFIX,
        silver_prefix=SILVER_PREFIX,
    )


# ==========================================================================================
# Happy path
# ==========================================================================================
class TestSilverOutput:
    def test_writes_both_datasets_to_the_expected_partitioned_keys(self, s3, transformer):
        put_raw(s3, sorteo=3046, year=2024)
        run(transformer)

        assert keys_under(s3, PARTITIONED, SILVER_PREFIX) == [
            "silver/premios/year=2024/sorteo=3046/premios.parquet",
            "silver/sorteos/year=2024/sorteo=3046/sorteos.parquet",
        ]


class TestSilverIsTheOnlyWriteTarget:
    """PR-041.2 — fault A, finished.

    PR-041.1 turned the duplicate write off with a flag and kept every byte. This is where
    the write path itself goes, and these tests are the acceptance criterion the roadmap's
    PR-041 prompt asked for: the transformer writes to exactly one bucket. Still nothing
    here deletes anything — the bytes are PR-041.3's business.
    """

    def test_nothing_is_written_to_the_second_bucket(self, s3, transformer):
        put_raw(s3, sorteo=3046, year=2024)
        run(transformer)

        assert s3.list_objects_v2(Bucket=OTHER_BUCKET).get("KeyCount") == 0

    def test_a_full_run_touches_exactly_one_bucket(self, s3, transformer):
        """The general form of the test above: whatever keys a run produces, all of them
        live under the partitioned bucket's Silver prefix. Written against the whole
        bucket rather than a prefix so that a stray write to raw/ or gold/ fails it too."""
        put_raw(s3, sorteo=3046, year=2024)
        run(transformer)

        written = {
            o["Key"]
            for o in s3.list_objects_v2(Bucket=PARTITIONED).get("Contents", [])
            if not o["Key"].startswith(RAW_PREFIX)
        }

        assert written == {
            "silver/premios/year=2024/sorteo=3046/premios.parquet",
            "silver/sorteos/year=2024/sorteo=3046/sorteos.parquet",
        }
        assert s3.list_objects_v2(Bucket=OTHER_BUCKET).get("KeyCount") == 0

    def test_silver_is_written_exactly_as_before(self, s3, transformer):
        """Removing the duplicate must change ONE thing. Silver is the canonical layer and
        the only input Gold has; if dropping the second write touched it at all, this PR
        would be a data change wearing a cleanup's clothes."""
        put_raw(s3, sorteo=3046, year=2024)
        run(transformer)

        assert keys_under(s3, PARTITIONED, SILVER_PREFIX) == [
            "silver/premios/year=2024/sorteo=3046/premios.parquet",
            "silver/sorteos/year=2024/sorteo=3046/sorteos.parquet",
        ]

    def test_flat_copies_from_before_the_retirement_are_left_untouched(self, s3, transformer):
        """ "Stop the writes, keep every byte" survives into this PR. A draw captured
        before PR-041.1's flip keeps its copy: this removes a write path, not data.
        PR-041.3 is where bytes go, after a stated grace period and its own runbook."""
        s3.put_object(Bucket=OTHER_BUCKET, Key="processed/sorteos_3045.parquet", Body=b"older")
        put_raw(s3, sorteo=3046, year=2024)

        run(transformer)

        assert keys_under(s3, OTHER_BUCKET, OTHER_BUCKET_PREFIX) == [
            "processed/sorteos_3045.parquet"
        ]

    def test_row_counts_match_the_source_file(self, s3, transformer):
        put_raw(s3, sorteo=3046, year=2024)
        run(transformer)

        premios = read_parquet(
            s3, PARTITIONED, "silver/premios/year=2024/sorteo=3046/premios.parquet"
        )
        sorteos = read_parquet(
            s3, PARTITIONED, "silver/sorteos/year=2024/sorteo=3046/sorteos.parquet"
        )

        assert len(premios) == 875  # same count test_parser.py pins for this fixture
        assert len(sorteos) == 1

    def test_processes_every_raw_file_present(self, s3, transformer):
        put_raw(s3, sorteo=3046, year=2024, fixture="ordinario_3046.txt")
        put_raw(s3, sorteo=413, year=2026, fixture="extraordinario_413.txt")
        run(transformer)

        assert keys_under(s3, PARTITIONED, "silver/sorteos/") == [
            "silver/sorteos/year=2024/sorteo=3046/sorteos.parquet",
            "silver/sorteos/year=2026/sorteo=413/sorteos.parquet",
        ]


# ==========================================================================================
# Schema
# ==========================================================================================
class TestSchema:
    def test_premios_columns_are_exactly_the_canonical_set_in_order(self, s3, transformer):
        put_raw(s3, sorteo=3046, year=2024)
        run(transformer)

        df = read_parquet(s3, PARTITIONED, "silver/premios/year=2024/sorteo=3046/premios.parquet")
        assert list(df.columns) == PREMIOS_COLUMNS

    def test_sorteos_columns_are_exactly_the_canonical_set_in_order(self, s3, transformer):
        put_raw(s3, sorteo=3046, year=2024)
        run(transformer)

        df = read_parquet(s3, PARTITIONED, "silver/sorteos/year=2024/sorteo=3046/sorteos.parquet")
        assert list(df.columns) == SORTEOS_COLUMNS

    def test_premios_parquet_types_match(self, s3, transformer):
        put_raw(s3, sorteo=3046, year=2024)
        run(transformer)

        schema = read_schema(
            s3, PARTITIONED, "silver/premios/year=2024/sorteo=3046/premios.parquet"
        )
        assert_parquet_types(schema, PREMIOS_PARQUET_TYPES)

    def test_sorteos_parquet_types_match(self, s3, transformer):
        put_raw(s3, sorteo=3046, year=2024)
        run(transformer)

        schema = read_schema(
            s3, PARTITIONED, "silver/sorteos/year=2024/sorteo=3046/sorteos.parquet"
        )
        assert_parquet_types(schema, SORTEOS_PARQUET_TYPES)

    def test_numero_premiado_is_nullable_in_parquet(self, s3, transformer):
        """Not cosmetic: the parser emits ticket numbers as text with leading zeros, and the
        transformer casts to a NULLABLE Int64 rather than int. A non-nullable cast would
        raise the day a prize row has no parseable number."""
        put_raw(s3, sorteo=3046, year=2024)
        run(transformer)

        schema = read_schema(
            s3, PARTITIONED, "silver/premios/year=2024/sorteo=3046/premios.parquet"
        )
        assert schema.field("numero_premiado").nullable

    def test_reintegros_is_exploded_into_three_int_columns(self, s3, transformer):
        put_raw(s3, sorteo=3046, year=2024)
        run(transformer)

        df = read_parquet(s3, PARTITIONED, "silver/sorteos/year=2024/sorteo=3046/sorteos.parquet")

        assert "reintegros" not in df.columns
        # Raw header for 3046 is "REINTEGROS 3,1 ,7" — irregular spacing, three values.
        assert df.loc[0, "reintegro_primer_premio"] == 3
        assert df.loc[0, "reintegro_segundo_premio"] == 1
        assert df.loc[0, "reintegro_tercer_premio"] == 7

    # PR-035: the padding branch of the reintegros split. The header regex is
    # `REINTEGROS ([\d, ]+)`, so a draw that publishes fewer than three reintegros produces
    # a split with fewer than three columns — and the Silver schema is fixed at three. Every
    # real capture so far has exactly three, which is why this path had never run.
    #
    # It matters because the alternative to padding is a KeyError deep inside the transform,
    # after the raw file has been read and before anything is written: the run fails, and the
    # traceback points at `reintegro_split[1]` rather than at the site publishing a short
    # header.
    @pytest.mark.parametrize(
        ("reintegros", "expected"),
        [
            ("REINTEGROS 3,1 ,7", (3, 1, 7)),
            ("REINTEGROS 3,1", (3, 1, None)),
            ("REINTEGROS 3", (3, None, None)),
        ],
    )
    def test_a_short_reintegros_header_is_padded_to_three_columns(
        self, s3, transformer, reintegros, expected
    ):
        body = (FIXTURES / "ordinario_3046.txt").read_text(encoding="utf-8")
        body = body.replace("REINTEGROS 3,1 ,7", reintegros)
        put_raw(s3, sorteo=3046, year=2024, body=body)
        run(transformer)

        df = read_parquet(s3, PARTITIONED, "silver/sorteos/year=2024/sorteo=3046/sorteos.parquet")
        actual = (
            df.loc[0, "reintegro_primer_premio"],
            df.loc[0, "reintegro_segundo_premio"],
            df.loc[0, "reintegro_tercer_premio"],
        )

        for got, want in zip(actual, expected, strict=True):
            if want is None:
                assert pd.isna(got)
            else:
                assert got == want

    def test_the_three_reintegro_columns_exist_even_when_the_header_is_short(self, s3, transformer):
        """The Silver schema must not change shape with the input. A missing column would
        make this Parquet file incompatible with every other one in the same prefix, which
        is the one thing the module docstring says never to do."""
        body = (FIXTURES / "ordinario_3046.txt").read_text(encoding="utf-8")
        body = body.replace("REINTEGROS 3,1 ,7", "REINTEGROS 3")
        put_raw(s3, sorteo=3046, year=2024, body=body)
        run(transformer)

        df = read_parquet(s3, PARTITIONED, "silver/sorteos/year=2024/sorteo=3046/sorteos.parquet")
        assert list(df.columns) == SORTEOS_COLUMNS

    def test_a_header_with_no_reintegros_line_at_all_is_rejected_by_the_parser(
        self, s3, transformer
    ):
        """⚠️ Two findings in one test (PR-035).

        First: ``transformer.py``'s ``else`` branch — the one that fills the three reintegro
        columns with None when the column is absent — **cannot be reached from the
        pipeline**. The only producer of that DataFrame is ``process_header``, and it treats
        a missing ``REINTEGROS`` as a malformed header and raises. The branch is a defensive
        leftover; it is listed with the other dead ends in pyproject.toml rather than
        exercised through a back door that production does not have.

        Second, and the reason this is asserted rather than deleted: that rejection takes
        **the whole run** with it. One unparseable raw file aborts the transform for every
        other file in the batch, before anything is written. A draw type that omits the line
        — or a redesign that renames the label — is a full weekly outage, not a skipped
        record. That is fault E's territory (PR-044, `quarantine/`), and this is the test
        that has to change when the quarantine lands.
        """
        body = (FIXTURES / "ordinario_3046.txt").read_text(encoding="utf-8")
        body = "\n".join(
            line for line in body.splitlines() if not line.strip().startswith("REINTEGROS")
        )
        put_raw(s3, sorteo=3046, year=2024, body=body)

        with pytest.raises(ValueError, match="HEADER does not contain the expected format"):
            run(transformer)

        assert s3.list_objects_v2(Bucket=PARTITIONED, Prefix="silver/").get("Contents", []) == []

    def test_dates_are_parsed_from_day_first_format(self, s3, transformer):
        put_raw(s3, sorteo=3046, year=2024)
        run(transformer)

        df = read_parquet(s3, PARTITIONED, "silver/sorteos/year=2024/sorteo=3046/sorteos.parquet")
        # "01/06/2024" is 1 June, not 6 January. Getting this backwards would silently
        # misfile the year partition for a third of the calendar.
        assert df.loc[0, "fecha_sorteo"] == pd.Timestamp("2024-06-01")
        assert df.loc[0, "fecha_caducidad"] == pd.Timestamp("2024-12-02")

    def test_capital_rows_get_guatemala_as_departamento(self, s3, transformer):
        put_raw(s3, sorteo=3046, year=2024)
        run(transformer)

        df = read_parquet(s3, PARTITIONED, "silver/premios/year=2024/sorteo=3046/premios.parquet")
        capital = df[df["ciudad"].fillna("").str.upper() == "DE ESTA CAPITAL"]

        assert not capital.empty, "fixture should contain 'DE ESTA CAPITAL' rows"
        assert (capital["departamento"] == "GUATEMALA").all()

    def test_unsold_prizes_survive_with_null_geography(self, s3, transformer):
        put_raw(s3, sorteo=3046, year=2024)
        run(transformer)

        df = read_parquet(s3, PARTITIONED, "silver/premios/year=2024/sorteo=3046/premios.parquet")
        unsold = df[df["vendedor"] == "NO VENDIDO"]

        assert len(unsold) == 19  # matches test_parser.py's count for this fixture
        assert unsold["ciudad"].isna().all()
        assert unsold["departamento"].isna().all()


# ==========================================================================================
# Partitioning
# ==========================================================================================
class TestYearPartition:
    def test_year_comes_from_fecha_sorteo_not_from_the_raw_path(self, s3, transformer):
        """The most load-bearing assertion in this file.

        Silver is partitioned by ``(year, sorteo)`` and the gold CTAS read those partitions.
        The year is derived from the parsed ``fecha_sorteo``, **not** from the ``year=`` in
        the raw key — so a raw file filed under the wrong year still lands in the right
        Silver partition. Filing this under year=1999 proves the derivation rather than
        letting a coincidence (raw year == fecha year, true for every real file) pass for a
        test.
        """
        put_raw(s3, sorteo=3046, year=1999)
        run(transformer)

        keys = keys_under(s3, PARTITIONED, SILVER_PREFIX)
        assert all("year=2024" in k for k in keys), keys
        assert not any("year=1999" in k for k in keys)

    def test_sorteo_number_comes_from_the_path_not_the_header(self, s3, transformer):
        # transform() reads sorteo=(\d+) from the KEY to decide idempotency and the output
        # partition, while numero_sorteo inside the data comes from the header. They agree in
        # production; this pins which one drives the path.
        put_raw(s3, sorteo=3046, year=2024)
        run(transformer)

        assert "sorteo=3046" in keys_under(s3, PARTITIONED, "silver/sorteos/")[0]


# ==========================================================================================
# Idempotency + skipping
# ==========================================================================================
class TestIdempotency:
    def test_the_extractor_guard_finds_what_the_transformer_wrote(self, s3, transformer):
        """PR-035.1 A. The extractor's guard and the transformer's writer each spell the
        Silver path themselves (s3_utils cannot import the transformer). This is the test
        that fails if they drift apart again, the way processed/ → silver/ once did."""
        from loteria.common.s3_utils import check_if_sorteo_exists

        assert check_if_sorteo_exists(PARTITIONED, 2024, 3046) is False
        put_raw(s3, sorteo=3046, year=2024)
        run(transformer)

        assert check_if_sorteo_exists(PARTITIONED, 2024, 3046) is True

    def test_second_run_skips_an_already_processed_sorteo(self, s3, transformer):
        put_raw(s3, sorteo=3046, year=2024)
        run(transformer)

        key = "silver/premios/year=2024/sorteo=3046/premios.parquet"
        first = s3.head_object(Bucket=PARTITIONED, Key=key)["LastModified"]

        run(transformer)  # the weekly pipeline re-scans the whole raw/ prefix every time
        second = s3.head_object(Bucket=PARTITIONED, Key=key)["LastModified"]

        assert first == second, "sorteo was rewritten instead of skipped"

    def test_a_new_sorteo_is_still_processed_when_others_exist(self, s3, transformer):
        put_raw(s3, sorteo=3046, year=2024)
        run(transformer)

        put_raw(s3, sorteo=413, year=2026, fixture="extraordinario_413.txt")
        run(transformer)

        assert len(keys_under(s3, PARTITIONED, "silver/sorteos/")) == 2

    def test_files_with_an_unexpected_key_shape_are_skipped_not_fatal(self, s3, transformer):
        # No sorteo=NNNN segment -> the regex misses -> warn and continue. One malformed
        # object must not stop the rest of the week's load.
        s3.put_object(
            Bucket=PARTITIONED,
            Key=f"{RAW_PREFIX}stray_file.txt",
            Body=(FIXTURES / "ordinario_3046.txt").read_bytes(),
        )
        put_raw(s3, sorteo=3046, year=2024)

        run(transformer)

        assert len(keys_under(s3, PARTITIONED, "silver/sorteos/")) == 1

    def test_non_txt_objects_are_ignored(self, s3, transformer):
        s3.put_object(
            Bucket=PARTITIONED, Key=f"{RAW_PREFIX}year=2024/sorteo=3046/notes.json", Body=b"{}"
        )
        put_raw(s3, sorteo=3046, year=2024)

        run(transformer)

        assert len(keys_under(s3, PARTITIONED, "silver/sorteos/")) == 1

    def test_empty_raw_prefix_is_a_no_op(self, s3, transformer):
        run(transformer)
        assert keys_under(s3, PARTITIONED, SILVER_PREFIX) == []


# ==========================================================================================
# Failure paths
# ==========================================================================================
class TestFailureModes:
    def test_invalid_fecha_sorteo_raises_valueerror(self, s3, transformer):
        """An unparseable date must fail loudly, not silently misfile the partition.

        ``pd.to_datetime(..., errors="coerce")`` turns a bad date into ``NaT``; without the
        explicit guard the year derivation would raise something opaque, or worse, a future
        refactor could default it. The message has to name the sorteo to be actionable.
        """
        body = (FIXTURES / "ordinario_3046.txt").read_text(encoding="utf-8")
        broken = body.replace("FECHA DEL SORTEO: 01/06/2024", "FECHA DEL SORTEO: 99/99/9999")
        put_raw(s3, sorteo=3046, year=2024, body=broken)

        with pytest.raises(ValueError, match=r"Invalid fecha_sorteo for sorteo=3046"):
            run(transformer)

    def test_nothing_is_written_when_the_date_is_invalid(self, s3, transformer):
        body = (FIXTURES / "ordinario_3046.txt").read_text(encoding="utf-8")
        broken = body.replace("FECHA DEL SORTEO: 01/06/2024", "FECHA DEL SORTEO: 99/99/9999")
        put_raw(s3, sorteo=3046, year=2024, body=broken)

        with pytest.raises(ValueError):
            run(transformer)

        # The guard sits before the Parquet write, so a half-transformed sorteo never
        # reaches Silver — the crawlers can't register a partition that isn't there.
        assert keys_under(s3, PARTITIONED, SILVER_PREFIX) == []
        assert keys_under(s3, OTHER_BUCKET, OTHER_BUCKET_PREFIX) == []

    def test_malformed_file_without_header_raises(self, s3, transformer):
        put_raw(s3, sorteo=3046, year=2024, body="just some text\nwith no markers\n")

        with pytest.raises(ValueError, match="HEADER or BODY"):
            run(transformer)


# ==========================================================================================
# The Glue entry point (PR-035)
# ==========================================================================================
class TestGlueEntryPoint:
    """``main()`` is the seam between Glue and ``transform()``, and it is the only place the
    job's arguments are named.

    Worth testing on its own because the failure mode is invisible locally: rename an
    argument in Terraform's ``default_arguments`` and nothing here breaks, but the weekly
    Glue run dies at ``getResolvedOptions`` before a line of transform logic executes.

    ``tests/conftest.py`` stubs ``getResolvedOptions`` to RAISE, deliberately — so that a
    test wandering into ``main()`` by accident gets a loud TypeError instead of a silently
    empty options dict. These tests opt in by replacing it explicitly.
    """

    @pytest.fixture
    def glue_main(self, transformer, monkeypatch):
        """Run ``main()`` with a given set of Glue job arguments, capturing the transform."""

        def _run(args, argv=None):
            monkeypatch.setattr(transformer, "getResolvedOptions", lambda _argv, _names: args)
            monkeypatch.setattr(sys, "argv", argv or ["transformer.py"])

            captured = {}
            monkeypatch.setattr(transformer, "transform", lambda **kwargs: captured.update(kwargs))

            transformer.main()
            return captured

        return _run

    ARGS = {
        "PARTITIONED_BUCKET": "arg-partitioned-bucket",
        "RAW_PREFIX": "raw/",
    }

    def test_it_transforms_the_partitioned_bucket(self, glue_main):
        assert glue_main(self.ARGS)["bucket_name"] == "arg-partitioned-bucket"

    def test_the_raw_prefix_is_passed_through(self, glue_main):
        assert glue_main(self.ARGS)["raw_prefix"] == "raw/"

    def test_transform_is_called_with_exactly_the_surviving_parameters(self, glue_main):
        """PR-041.2 removed `simple_prefix` and `write_simple_copies` from transform()'s
        signature. Pinning the whole keyword set — not just the ones that matter — is what
        makes a re-added parameter fail here instead of quietly coming back."""
        assert set(glue_main(self.ARGS)) == {"bucket_name", "raw_prefix", "silver_prefix"}

    def test_silver_prefix_is_not_an_argument(self, glue_main):
        """Silver is the canonical layer and its location is a code constant, not a knob.
        Making it settable per-run is how you end up with two prefixes holding two schemas —
        the one thing the module docstring forbids."""
        assert glue_main(self.ARGS)["silver_prefix"] == transformer_module_silver_prefix()

    def test_the_bucket_argument_overrides_the_import_time_secret(self, glue_main, transformer):
        """`transform()` READS its bucket from an argument but WRITES to a module global. If
        main() failed to override it, the job would read from the argument bucket and write
        to whatever the Secrets Manager payload said at import — a split-brain that only
        shows up in production."""
        glue_main(self.ARGS)

        assert transformer.partitioned_bucket == "arg-partitioned-bucket"

    def test_an_empty_bucket_argument_leaves_the_global_alone(self, glue_main, transformer):
        """The override is guarded by a truthiness check, so an empty value falls back to
        the secret rather than pointing the job at a bucket named ""."""
        glue_main({**self.ARGS, "PARTITIONED_BUCKET": ""})

        assert transformer.partitioned_bucket == PARTITIONED

    def test_it_asks_glue_for_exactly_the_two_documented_arguments(self, transformer, monkeypatch):
        """These names are the contract with terraform/modules/etl-glue's
        `default_arguments`. Adding one here without adding it there fails the job at
        startup.

        PR-041.2 took this set from four to two. The three it dropped can still be sitting
        in a not-yet-applied job definition and the job starts anyway, because
        getResolvedOptions ignores arguments that were not asked for — it only raises the
        other way round, on a name it is asked for and cannot find."""
        requested = self._requested_names(transformer, monkeypatch, argv=["transformer.py"])

        assert set(requested) == {
            "PARTITIONED_BUCKET",
            "RAW_PREFIX",
        }

    def _requested_names(self, transformer, monkeypatch, argv):
        requested = {}

        def fake_resolve(_argv, names):
            requested["names"] = names
            return self.ARGS

        monkeypatch.setattr(transformer, "getResolvedOptions", fake_resolve)
        monkeypatch.setattr(sys, "argv", argv)
        monkeypatch.setattr(transformer, "transform", lambda **kwargs: None)

        transformer.main()
        return requested["names"]


def transformer_module_silver_prefix() -> str:
    """The Silver prefix constant, read without importing the module at collection time."""
    return "silver/"
