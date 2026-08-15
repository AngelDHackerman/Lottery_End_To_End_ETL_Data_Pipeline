"""Tests for the gold CTAS pre-flight Lambda (PR-035).

``loteria.gold.purge_and_load`` runs once per gold table inside the ``BuildGold`` Map. It is
the most destructive code in the repo — it hard-deletes every object *version* under a gold
prefix — and it was untested.

Two behaviours are worth stating plainly, because both look wrong until you know why:

* it deletes **versions**, not objects. The bucket is versioned (PR-002/005), so a plain
  delete leaves delete-markers and Athena still refuses the location with
  ``HIVE_PATH_ALREADY_EXISTS``. Gold is derived data, rebuilt from Silver every run, so
  hard-deleting it is safe.
* it must delete **only** under the CTAS target prefix. A prefix bug here would take out
  Silver, which is not reproducible from anything but a re-scrape of a site that only shows
  the latest draw.

``boto3.client`` is called at module import, so the module is imported inside ``mock_aws``.
"""

from __future__ import annotations

import importlib
import sys

import boto3
import pytest
from moto import mock_aws

REGION = "us-east-1"
BUCKET = "lottery-partitioned-storage-prod"

SQL = """-- gold: draw summary
DROP TABLE IF EXISTS lottery_santalucia_db.gold_draw_summary;

CREATE TABLE lottery_santalucia_db.gold_draw_summary
WITH (
  format = 'PARQUET',
  external_location = 's3://lottery-partitioned-storage-prod/gold/draw_summary/'
) AS
SELECT numero_sorteo FROM lottery_santalucia_db.silver_sorteos_sorteos;
"""


@pytest.fixture
def gold():
    """Import the module with a live moto S3 + Glue, and both clients bound to them.

    The module builds its `s3` and `glue` clients at import time, so it has to be imported
    while the mock is active and evicted afterwards.
    """
    with mock_aws():
        boto3.client("s3", region_name=REGION).create_bucket(Bucket=BUCKET)
        boto3.client("s3", region_name=REGION).put_bucket_versioning(
            Bucket=BUCKET, VersioningConfiguration={"Status": "Enabled"}
        )
        boto3.client("glue", region_name=REGION).create_database(
            DatabaseInput={"Name": "lottery_santalucia_db"}
        )

        sys.modules.pop("loteria.gold.purge_and_load", None)
        module = importlib.import_module("loteria.gold.purge_and_load")

        yield module

        sys.modules.pop("loteria.gold.purge_and_load", None)


@pytest.fixture
def s3(gold):
    return gold.s3


def put_sql(s3, key="sql/gold/01_gold_draw_summary.sql", body=SQL):
    s3.put_object(Bucket=BUCKET, Key=key, Body=body.encode("utf-8"))
    return key


def write_versions(s3, key, n=3):
    """Write the same key n times so it accumulates n versions."""
    for i in range(n):
        s3.put_object(Bucket=BUCKET, Key=key, Body=f"v{i}".encode())


# ==========================================================================================
# Parsing the SQL
# ==========================================================================================
class TestExtractCreateStatement:
    def test_drops_everything_before_the_create(self, gold):
        """Athena's StartQueryExecution takes ONE statement. The SQL files carry
        `DROP ...; CREATE ...`, so passing the file through verbatim fails."""
        statement = gold._extract_create_statement(SQL)

        assert statement.startswith("CREATE TABLE")
        assert "DROP TABLE" not in statement

    def test_strips_the_trailing_semicolon(self, gold):
        """Athena rejects a trailing semicolon."""
        assert not gold._extract_create_statement(SQL).endswith(";")

    def test_keeps_the_select_body(self, gold):
        assert "silver_sorteos_sorteos" in gold._extract_create_statement(SQL)

    def test_a_file_without_a_create_raises(self, gold):
        with pytest.raises(ValueError, match="CREATE TABLE"):
            gold._extract_create_statement("SELECT 1;")


# ==========================================================================================
# Emptying the prefix
# ==========================================================================================
class TestEmptyPrefix:
    def test_deletes_every_version_not_just_the_current_one(self, gold, s3):
        """The reason this helper exists. A plain delete on a versioned bucket adds a
        delete-marker and leaves the data, and Athena still fails with
        HIVE_PATH_ALREADY_EXISTS at a location that looks empty in the console."""
        write_versions(s3, "gold/draw_summary/part-0.parquet", n=3)

        gold._empty_prefix(BUCKET, "gold/draw_summary/")

        versions = s3.list_object_versions(Bucket=BUCKET, Prefix="gold/draw_summary/")
        assert versions.get("Versions", []) == []
        assert versions.get("DeleteMarkers", []) == []

    def test_returns_the_number_deleted(self, gold, s3):
        write_versions(s3, "gold/draw_summary/part-0.parquet", n=3)

        assert gold._empty_prefix(BUCKET, "gold/draw_summary/") == 3

    def test_an_already_empty_prefix_is_a_no_op(self, gold):
        """Idempotency: the Map may retry, and the first successful purge leaves nothing."""
        assert gold._empty_prefix(BUCKET, "gold/draw_summary/") == 0

    def test_it_does_not_touch_a_sibling_prefix(self, gold, s3):
        """`gold/draw_summary/` and `gold/draw_summary_v2/` share a string prefix. A missing
        trailing slash in the SQL would silently purge the neighbour."""
        write_versions(s3, "gold/draw_summary/part-0.parquet", n=1)
        write_versions(s3, "gold/terminations/part-0.parquet", n=2)

        gold._empty_prefix(BUCKET, "gold/draw_summary/")

        assert (
            len(s3.list_object_versions(Bucket=BUCKET, Prefix="gold/terminations/")["Versions"])
            == 2
        )

    def test_it_does_not_touch_silver(self, gold, s3):
        """The one that would be unrecoverable. Silver cannot be rebuilt from anything except
        a re-scrape of a site that only publishes the latest draw."""
        write_versions(s3, "silver/sorteos/year=2024/sorteo=3046/sorteos.parquet", n=1)
        write_versions(s3, "gold/draw_summary/part-0.parquet", n=1)

        gold._empty_prefix(BUCKET, "gold/draw_summary/")

        assert len(s3.list_object_versions(Bucket=BUCKET, Prefix="silver/")["Versions"]) == 1

    def test_a_refused_delete_raises_instead_of_under_deleting(self, gold, monkeypatch):
        """The PR-002 bucket Deny policy can block these. Silently under-deleting would let
        the CTAS run into a non-empty location and fail far from the cause."""
        monkeypatch.setattr(
            gold.s3,
            "delete_objects",
            lambda **kw: {"Errors": [{"Code": "AccessDenied", "Message": "no", "Key": "k"}]},
        )
        write_versions(gold.s3, "gold/draw_summary/part-0.parquet", n=1)

        with pytest.raises(RuntimeError, match="AccessDenied"):
            gold._empty_prefix(BUCKET, "gold/draw_summary/")


# ==========================================================================================
# Dropping the table
# ==========================================================================================
class TestDropTable:
    def test_returns_true_when_a_table_was_removed(self, gold):
        gold.glue.create_table(
            DatabaseName="lottery_santalucia_db",
            TableInput={"Name": "gold_draw_summary"},
        )

        assert gold._drop_table("lottery_santalucia_db", "gold_draw_summary") is True

    def test_a_missing_table_is_not_an_error(self, gold):
        """Mirrors DROP TABLE IF EXISTS. The first ever run has no table to drop, and a raise
        there would fail the whole Map iteration."""
        assert gold._drop_table("lottery_santalucia_db", "never_existed") is False


# ==========================================================================================
# The handler
# ==========================================================================================
class TestHandler:
    def test_returns_the_create_statement_for_athena(self, gold, s3):
        key = put_sql(s3)
        result = gold.handler({"bucket": BUCKET, "sqlKey": key}, None)

        assert result["queryString"].startswith("CREATE TABLE")

    def test_reports_the_table_and_location_parsed_from_the_sql(self, gold, s3):
        """The SQL file is the single source of truth — table name and location are parsed
        from it rather than duplicated in Terraform."""
        key = put_sql(s3)
        result = gold.handler({"bucket": BUCKET, "sqlKey": key}, None)

        assert result["database"] == "lottery_santalucia_db"
        assert result["table"] == "gold_draw_summary"
        assert result["location"] == f"s3://{BUCKET}/gold/draw_summary/"

    def test_it_empties_the_target_location(self, gold, s3):
        key = put_sql(s3)
        write_versions(s3, "gold/draw_summary/part-0.parquet", n=2)

        result = gold.handler({"bucket": BUCKET, "sqlKey": key}, None)

        assert result["objectsDeleted"] == 2
        assert (
            s3.list_object_versions(Bucket=BUCKET, Prefix="gold/draw_summary/").get("Versions", [])
            == []
        )

    def test_it_drops_the_catalog_table(self, gold, s3):
        key = put_sql(s3)
        gold.glue.create_table(
            DatabaseName="lottery_santalucia_db", TableInput={"Name": "gold_draw_summary"}
        )

        gold.handler({"bucket": BUCKET, "sqlKey": key}, None)

        with pytest.raises(gold.glue.exceptions.EntityNotFoundException):
            gold.glue.get_table(DatabaseName="lottery_santalucia_db", Name="gold_draw_summary")

    def test_sql_without_an_external_location_raises(self, gold, s3):
        """Without it the Lambda has no idea what to purge, and a CTAS onto a non-empty
        location fails. Better to stop here, where the message names the file."""
        key = put_sql(s3, key="sql/gold/bad.sql", body="CREATE TABLE db.t AS SELECT 1;")

        with pytest.raises(ValueError, match="external_location"):
            gold.handler({"bucket": BUCKET, "sqlKey": key}, None)

    def test_sql_without_a_create_table_raises(self, gold, s3):
        body = "WITH (external_location = 's3://b/p/') AS SELECT 1;"
        key = put_sql(s3, key="sql/gold/bad2.sql", body=body)

        with pytest.raises(ValueError, match="CREATE TABLE"):
            gold.handler({"bucket": BUCKET, "sqlKey": key}, None)

    def test_a_correlation_id_from_the_event_is_accepted(self, gold, s3):
        """PR-018: the Map passes the execution name so these log lines join the rest of the
        run. Purely a logging concern, but a KeyError here would fail the iteration."""
        key = put_sql(s3)
        result = gold.handler({"bucket": BUCKET, "sqlKey": key, "correlation_id": "exec-1"}, None)

        assert result["table"] == "gold_draw_summary"

    def test_it_works_without_a_correlation_id(self, gold, s3, monkeypatch):
        monkeypatch.delenv("CORRELATION_ID", raising=False)
        key = put_sql(s3)

        assert gold.handler({"bucket": BUCKET, "sqlKey": key}, None)["table"] == "gold_draw_summary"

    def test_running_twice_is_safe(self, gold, s3):
        """The Map retries on transient Athena failures, so the second run must not blow up
        on an already-dropped table or an already-empty prefix."""
        key = put_sql(s3)
        write_versions(s3, "gold/draw_summary/part-0.parquet", n=1)

        first = gold.handler({"bucket": BUCKET, "sqlKey": key}, None)
        second = gold.handler({"bucket": BUCKET, "sqlKey": key}, None)

        assert first["objectsDeleted"] == 1
        assert second["objectsDeleted"] == 0
        assert first["queryString"] == second["queryString"]
