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
SIMPLE = "test-simple-bucket"
RAW_PREFIX = "raw/"
SIMPLE_PREFIX = "processed/"
SILVER_PREFIX = "silver/"

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
        lambda: {"partitioned": PARTITIONED, "simple": SIMPLE},
    )
    sys.modules.pop("loteria.transformer.transformer", None)

    mod = importlib.import_module("loteria.transformer.transformer")

    # transform() reads from its `bucket_name` argument but WRITES to these module globals.
    # Set them explicitly: a test that only passed bucket_name would silently write to
    # whatever the import-time secret returned.
    monkeypatch.setattr(mod, "partitioned_bucket", PARTITIONED)
    monkeypatch.setattr(mod, "simple_bucket", SIMPLE)

    yield mod

    sys.modules.pop("loteria.transformer.transformer", None)


@pytest.fixture
def s3():
    """Both buckets, empty, in an in-process fake S3."""
    with mock_aws():
        client = boto3.client("s3", region_name=REGION)
        client.create_bucket(Bucket=PARTITIONED)
        client.create_bucket(Bucket=SIMPLE)
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
        simple_prefix=SIMPLE_PREFIX,
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

    def test_also_writes_flat_copies_to_the_simple_bucket(self, s3, transformer):
        put_raw(s3, sorteo=3046, year=2024)
        run(transformer)

        assert keys_under(s3, SIMPLE, SIMPLE_PREFIX) == [
            "processed/premios_3046.parquet",
            "processed/sorteos_3046.parquet",
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
        assert keys_under(s3, SIMPLE, SIMPLE_PREFIX) == []

    def test_malformed_file_without_header_raises(self, s3, transformer):
        put_raw(s3, sorteo=3046, year=2024, body="just some text\nwith no markers\n")

        with pytest.raises(ValueError, match="HEADER or BODY"):
            run(transformer)
