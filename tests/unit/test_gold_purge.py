"""Tests for the Gold publication Lambda (PR-035, rewritten for blue/green in PR-042.1).

``loteria.gold.purge_and_load`` runs twice per gold table inside the ``BuildGold`` Map:
``prepare`` before the CTAS and ``promote`` after it. It is still the most destructive code
in the repo — it hard-deletes object *versions* — but what it is allowed to destroy changed
completely, and that is what most of this file is about.

Two behaviours look wrong until you know why:

* it deletes **versions**, not objects. The bucket is versioned (PR-002/005), so a plain
  delete leaves delete-markers and Athena still refuses the location with
  ``HIVE_PATH_ALREADY_EXISTS``. Gold is derived data, rebuilt from Silver every run.
* it must delete **only** under the prefix it was given. A prefix bug here would take out
  Silver, which is not reproducible from anything but a re-scrape of a site that only shows
  the latest draw.

**The property PR-042.1 adds, and the one worth breaking the build over:** nothing published
is touched until the CTAS has succeeded. ``TestNothingPublishedIsTouchedBeforeTheCTAS`` is
the acceptance criterion the roadmap states for this PR, expressed as tests — a failed build
must leave the live table serving its previous rows.

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


PARTITIONED_SQL = """-- gold: geo winnings
DROP TABLE IF EXISTS lottery_santalucia_db.gold_geo_winnings;

CREATE TABLE lottery_santalucia_db.gold_geo_winnings
WITH (
  format = 'PARQUET',
  external_location = 's3://lottery-partitioned-storage-prod/gold/geo_winnings/',
  partitioned_by = ARRAY['year']
) AS
SELECT departamento, year FROM lottery_santalucia_db.silver_premios_premios;
"""

RUN = "exec-1"

#: What the Lambda derives from RUN. Spelled out rather than imported so a change to the
#: naming scheme fails these tests instead of silently agreeing with itself.
STAGING_TABLE = "gold_draw_summary__stg_exec_1"
STAGING_PREFIX = "gold/draw_summary/run=exec_1/"


def prepare(gold, key, run=RUN, bucket=BUCKET):
    return gold.handler(
        {"action": "prepare", "bucket": bucket, "sqlKey": key, "correlation_id": run}, None
    )


def fake_ctas(gold, prepared, rows=("a",), partitions=()):
    """Stand in for Athena: create the staging table the CTAS would have created.

    Athena writes the Parquet AND registers the table; moto has no CTAS, so the effect is
    reproduced directly. The point of the tests below is what happens around that, not
    inside it.
    """
    location = prepared["location"]
    sd = {
        "Location": location,
        "Columns": [{"Name": "col", "Type": "string"}],
        "SerdeInfo": {"SerializationLibrary": "parquet"},
    }
    table_input = {
        "Name": prepared["stagingTable"],
        "StorageDescriptor": sd,
        "Parameters": {"rows": str(len(rows))},
    }
    if partitions:
        table_input["PartitionKeys"] = [{"Name": "year", "Type": "string"}]

    gold.glue.create_table(DatabaseName=prepared["database"], TableInput=table_input)

    for value in partitions:
        gold.glue.create_partition(
            DatabaseName=prepared["database"],
            TableName=prepared["stagingTable"],
            PartitionInput={
                "Values": [value],
                "StorageDescriptor": {**sd, "Location": f"{location}year={value}/"},
            },
        )
    return prepared


def publish_previous_generation(gold, table="gold_draw_summary", location=None, partitions=()):
    """A table already published at an older generation, as every run after the first finds."""
    location = location or f"s3://{BUCKET}/gold/draw_summary/run=older/"
    sd = {
        "Location": location,
        "Columns": [{"Name": "col", "Type": "string"}],
        "SerdeInfo": {"SerializationLibrary": "parquet"},
    }
    table_input = {"Name": table, "StorageDescriptor": sd, "Parameters": {"generation": "older"}}
    if partitions:
        table_input["PartitionKeys"] = [{"Name": "year", "Type": "string"}]

    gold.glue.create_table(DatabaseName="lottery_santalucia_db", TableInput=table_input)

    for value in partitions:
        gold.glue.create_partition(
            DatabaseName="lottery_santalucia_db",
            TableName=table,
            PartitionInput={
                "Values": [value],
                "StorageDescriptor": {**sd, "Location": f"{location}year={value}/"},
            },
        )
    return location


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
class TestPrepare:
    """Everything before the CTAS. None of it may touch anything published."""

    def test_returns_the_create_statement_for_athena(self, gold, s3):
        key = put_sql(s3)

        assert prepare(gold, key)["queryString"].startswith("CREATE TABLE")

    def test_reports_the_table_parsed_from_the_sql(self, gold, s3):
        """The SQL file is the single source of truth — table name and location are parsed
        from it rather than duplicated in Terraform. PR-042.1 keeps that property: the
        staging names are DERIVED from the file, not configured anywhere."""
        key = put_sql(s3)
        result = prepare(gold, key)

        assert result["database"] == "lottery_santalucia_db"
        assert result["table"] == "gold_draw_summary"
        assert result["publishedLocation"] == f"s3://{BUCKET}/gold/draw_summary/"

    def test_the_ctas_is_aimed_at_a_staging_table(self, gold, s3):
        key = put_sql(s3)
        result = prepare(gold, key)

        assert result["stagingTable"] == STAGING_TABLE
        assert f"CREATE TABLE lottery_santalucia_db.{STAGING_TABLE}" in result["queryString"]
        assert "CREATE TABLE lottery_santalucia_db.gold_draw_summary\n" not in result["queryString"]

    def test_the_ctas_is_aimed_at_a_staging_location(self, gold, s3):
        key = put_sql(s3)
        result = prepare(gold, key)

        assert result["location"] == f"s3://{BUCKET}/{STAGING_PREFIX}"
        assert f"external_location = 's3://{BUCKET}/{STAGING_PREFIX}'" in result["queryString"]

    def test_the_select_body_survives_the_rewrite(self, gold, s3):
        """Both substitutions are positional. A blind string replace of the table name would
        be free to corrupt the SELECT or the file's comments."""
        key = put_sql(s3)
        query = prepare(gold, key)["queryString"]

        assert "FROM lottery_santalucia_db.silver_sorteos_sorteos" in query
        assert query.count("CREATE TABLE") == 1

    def test_two_runs_get_two_staging_identities(self, gold, s3):
        key = put_sql(s3)

        first = prepare(gold, key, run="exec-1")
        second = prepare(gold, key, run="exec-2")

        assert first["stagingTable"] != second["stagingTable"]
        assert first["location"] != second["location"]

    def test_an_execution_name_is_made_safe_for_glue_and_s3(self, gold, s3):
        """Step Functions execution names carry hyphens and are two UUIDs long; Glue table
        names allow neither hyphens nor unbounded length."""
        key = put_sql(s3)
        result = prepare(gold, key, run="Abc-123_" + "x" * 100)

        slug = result["stagingTable"].split(gold.STAGING_SUFFIX)[1]
        assert slug.islower()
        assert "-" not in slug
        assert len(slug) <= gold.MAX_RUN_ID

    def test_sql_without_an_external_location_raises(self, gold, s3):
        """Without it there is nowhere to stage, and a CTAS onto a non-empty location fails.
        Better to stop here, where the message names the file."""
        key = put_sql(s3, key="sql/gold/bad.sql", body="CREATE TABLE db.t AS SELECT 1;")

        with pytest.raises(ValueError, match="external_location"):
            prepare(gold, key)

    def test_sql_without_a_create_table_raises(self, gold, s3):
        body = "WITH (external_location = 's3://b/p/') AS SELECT 1;"
        key = put_sql(s3, key="sql/gold/bad2.sql", body=body)

        with pytest.raises(ValueError, match="CREATE TABLE"):
            prepare(gold, key)

    def test_it_works_without_a_correlation_id(self, gold, s3, monkeypatch):
        monkeypatch.delenv("CORRELATION_ID", raising=False)
        key = put_sql(s3)

        result = gold.handler({"action": "prepare", "bucket": BUCKET, "sqlKey": key}, None)

        assert result["table"] == "gold_draw_summary"


class TestNothingPublishedIsTouchedBeforeTheCTAS:
    """**The acceptance criterion for PR-042.1**, and the whole reason it exists.

    The roadmap states it as "force a CTAS failure on one table and show the published table
    still returning its previous row count". A CTAS failure is a CTAS that never ran, so
    these call ``prepare`` and then stop — which is exactly the state a failed run leaves
    behind. Every one of them fails against the pre-PR-042.1 Lambda, which dropped the table
    and emptied its prefix before returning.
    """

    def test_the_published_table_still_exists(self, gold, s3):
        key = put_sql(s3)
        publish_previous_generation(gold)

        prepare(gold, key)  # ... and the CTAS fails here

        table = gold.glue.get_table(DatabaseName="lottery_santalucia_db", Name="gold_draw_summary")[
            "Table"
        ]
        assert table["Parameters"]["generation"] == "older"

    def test_the_published_table_still_points_at_its_own_data(self, gold, s3):
        key = put_sql(s3)
        location = publish_previous_generation(gold)

        prepare(gold, key)

        table = gold.glue.get_table(DatabaseName="lottery_santalucia_db", Name="gold_draw_summary")[
            "Table"
        ]
        assert table["StorageDescriptor"]["Location"] == location

    def test_the_published_parquet_is_still_there(self, gold, s3):
        """The seven-day hole, in one assertion. Before PR-042.1 these versions were hard
        deleted before Athena was even asked to run."""
        key = put_sql(s3)
        write_versions(s3, "gold/draw_summary/run=older/part-0.parquet", n=3)

        prepare(gold, key)

        versions = s3.list_object_versions(
            Bucket=BUCKET, Prefix="gold/draw_summary/run=older/"
        ).get("Versions", [])
        assert len(versions) == 3

    def test_nothing_is_deleted_at_all_on_a_clean_run(self, gold, s3):
        key = put_sql(s3)
        publish_previous_generation(gold)

        assert prepare(gold, key)["objectsDeleted"] == 0


class TestPrepareCleansOnlyItsOwnStagingPrefix:
    def test_a_failed_attempt_of_the_same_run_is_cleared(self, gold, s3):
        """Athena refuses a non-empty external_location, so a retried execution would trip
        over its own leftovers. This prefix is named for the execution, so it can only ever
        hold that execution's failed attempt — never published data."""
        key = put_sql(s3)
        write_versions(s3, f"{STAGING_PREFIX}part-0.parquet", n=2)

        result = prepare(gold, key)

        assert result["objectsDeleted"] == 2
        assert s3.list_object_versions(Bucket=BUCKET, Prefix=STAGING_PREFIX).get("Versions") is None

    def test_another_runs_staging_prefix_is_untouched(self, gold, s3):
        """Concurrency 3 means three of these run at once, and a retry may overlap a run
        that is still going. Each must only ever clear its own."""
        key = put_sql(s3)
        write_versions(s3, "gold/draw_summary/run=someone_else/part-0.parquet", n=1)

        prepare(gold, key)

        other = s3.list_object_versions(
            Bucket=BUCKET, Prefix="gold/draw_summary/run=someone_else/"
        ).get("Versions", [])
        assert len(other) == 1

    def test_a_stale_staging_table_from_a_failed_attempt_is_dropped(self, gold, s3):
        """Same reason as the prefix: CREATE TABLE fails if the name is taken, and the only
        way this name is taken is a previous attempt of this same execution."""
        key = put_sql(s3)
        gold.glue.create_table(
            DatabaseName="lottery_santalucia_db", TableInput={"Name": STAGING_TABLE}
        )

        prepare(gold, key)

        with pytest.raises(gold.glue.exceptions.EntityNotFoundException):
            gold.glue.get_table(DatabaseName="lottery_santalucia_db", Name=STAGING_TABLE)

    def test_running_prepare_twice_is_safe(self, gold, s3):
        key = put_sql(s3)
        write_versions(s3, f"{STAGING_PREFIX}part-0.parquet", n=1)

        first = prepare(gold, key)
        second = prepare(gold, key)

        assert first["objectsDeleted"] == 1
        assert second["objectsDeleted"] == 0
        assert first["queryString"] == second["queryString"]


class TestPromote:
    """The swap. Everything here runs only because the CTAS already succeeded."""

    def test_the_published_table_points_at_the_new_generation(self, gold, s3):
        key = put_sql(s3)
        publish_previous_generation(gold)
        prepared = fake_ctas(gold, prepare(gold, key))

        gold.handler({"action": "promote", **prepared, "correlation_id": RUN}, None)

        table = gold.glue.get_table(DatabaseName="lottery_santalucia_db", Name="gold_draw_summary")[
            "Table"
        ]
        assert table["StorageDescriptor"]["Location"] == prepared["location"]

    def test_the_previous_generation_is_left_in_s3(self, gold, s3):
        """The rollback, and PR-042.2's job to retire. A swap that deleted the old copy
        would be the same defect with better timing."""
        key = put_sql(s3)
        write_versions(s3, "gold/draw_summary/run=older/part-0.parquet", n=2)
        publish_previous_generation(gold)
        prepared = fake_ctas(gold, prepare(gold, key))

        gold.handler({"action": "promote", **prepared, "correlation_id": RUN}, None)

        versions = s3.list_object_versions(
            Bucket=BUCKET, Prefix="gold/draw_summary/run=older/"
        ).get("Versions", [])
        assert len(versions) == 2

    def test_the_staging_catalog_entry_is_removed(self, gold, s3):
        """Its DATA is now the published data; only the extra name goes."""
        key = put_sql(s3)
        prepared = fake_ctas(gold, prepare(gold, key))

        gold.handler({"action": "promote", **prepared, "correlation_id": RUN}, None)

        with pytest.raises(gold.glue.exceptions.EntityNotFoundException):
            gold.glue.get_table(DatabaseName="lottery_santalucia_db", Name=STAGING_TABLE)

    def test_a_first_run_creates_the_published_table(self, gold, s3):
        """No previous generation exists — the table has never been published."""
        key = put_sql(s3)
        prepared = fake_ctas(gold, prepare(gold, key))

        result = gold.handler({"action": "promote", **prepared, "correlation_id": RUN}, None)

        assert result["created"] is True
        assert gold.glue.get_table(DatabaseName="lottery_santalucia_db", Name="gold_draw_summary")

    def test_an_existing_table_is_updated_not_recreated(self, gold, s3):
        """UpdateTable is one API call and the table never stops existing. A
        drop-then-create would reintroduce a window, smaller but of the same kind."""
        key = put_sql(s3)
        publish_previous_generation(gold)
        prepared = fake_ctas(gold, prepare(gold, key))

        result = gold.handler({"action": "promote", **prepared, "correlation_id": RUN}, None)

        assert result["created"] is False

    def test_the_schema_comes_from_what_the_ctas_actually_built(self, gold, s3):
        """Not from the SQL file: if Athena produced different columns than the file implies,
        the catalog must describe the Parquet that exists, not the intent."""
        key = put_sql(s3)
        publish_previous_generation(gold)
        prepared = fake_ctas(gold, prepare(gold, key), rows=("a", "b", "c"))

        gold.handler({"action": "promote", **prepared, "correlation_id": RUN}, None)

        table = gold.glue.get_table(DatabaseName="lottery_santalucia_db", Name="gold_draw_summary")[
            "Table"
        ]
        assert table["Parameters"]["rows"] == "3"

    def test_an_unknown_action_is_refused(self, gold):
        with pytest.raises(ValueError, match="Unknown action"):
            gold.handler({"action": "purge_everything"}, None)

    def test_prepare_is_the_default_action(self, gold, s3):
        """The Step Function names it explicitly, but an operator invoking the Lambda by
        hand should get the harmless half."""
        key = put_sql(s3)

        result = gold.handler({"bucket": BUCKET, "sqlKey": key}, None)

        assert "queryString" in result


class TestPromotePartitionedTables:
    """The failure mode the roadmap flags for this PR: a table that reads EMPTY after a
    "successful" swap.

    A partitioned table's rows are found through its partitions, and each partition carries
    its own location. Repointing the table without repointing them publishes an empty table
    on top of a perfectly good generation.
    """

    def _promote(self, gold, s3, previous=("2024",), staged=("2024",)):
        key = put_sql(s3, key="sql/gold/05.sql", body=PARTITIONED_SQL)
        publish_previous_generation(
            gold,
            table="gold_geo_winnings",
            location=f"s3://{BUCKET}/gold/geo_winnings/run=older/",
            partitions=previous,
        )
        prepared = fake_ctas(gold, prepare(gold, key), partitions=staged)
        result = gold.handler({"action": "promote", **prepared, "correlation_id": RUN}, None)
        return prepared, result

    def _locations(self, gold):
        return {
            tuple(p["Values"]): p["StorageDescriptor"]["Location"]
            for p in gold.glue.get_partitions(
                DatabaseName="lottery_santalucia_db", TableName="gold_geo_winnings"
            )["Partitions"]
        }

    def test_partitions_follow_the_table_to_the_new_generation(self, gold, s3):
        prepared, _ = self._promote(gold, s3)

        assert self._locations(gold) == {("2024",): f"{prepared['location']}year=2024/"}

    def test_a_new_year_is_added(self, gold, s3):
        prepared, result = self._promote(gold, s3, previous=("2024",), staged=("2024", "2025"))

        assert result["partitions"] == {"updated": 1, "created": 1, "deleted": 0}
        assert set(self._locations(gold)) == {("2024",), ("2025",)}

    def test_a_year_the_new_generation_does_not_have_is_removed(self, gold, s3):
        """Otherwise the table keeps a partition pointing into the old generation, and a
        query silently mixes two builds — which is worse than either."""
        _, result = self._promote(gold, s3, previous=("2023", "2024"), staged=("2024",))

        assert result["partitions"] == {"updated": 1, "created": 0, "deleted": 1}
        assert set(self._locations(gold)) == {("2024",)}

    def test_an_existing_year_is_updated_rather_than_dropped_and_recreated(self, gold, s3):
        """The distinction that keeps the table from reading empty mid-swap: an update never
        passes through a state where the partition is absent."""
        _, result = self._promote(gold, s3, previous=("2024",), staged=("2024",))

        assert result["partitions"] == {"updated": 1, "created": 0, "deleted": 0}

    def test_an_unpartitioned_table_reports_no_partition_work(self, gold, s3):
        key = put_sql(s3)
        publish_previous_generation(gold)
        prepared = fake_ctas(gold, prepare(gold, key))

        result = gold.handler({"action": "promote", **prepared, "correlation_id": RUN}, None)

        assert result["partitions"] == {"updated": 0, "created": 0, "deleted": 0}


class TestTheGuardsInside:
    """Three defensive paths that `prepare`/`promote` cannot reach through the front door.

    They are tested directly rather than left uncovered because two of them are the
    difference between a loud failure and a silently half-swapped table.
    """

    def test_the_batch_guard_raises_on_per_partition_errors(self, gold):
        """**The important one.** Glue's batch APIs report per-item failures in the RESPONSE,
        not as an exception, so `resp.get("Errors")` is the only place a partial failure
        appears. Ignoring it is how a swap reports success while leaving the table pointing
        half at one generation and half at another — fault B with extra steps."""
        errors = [
            {
                "PartitionValues": ["2024"],
                "ErrorDetail": {"ErrorCode": "EntityNotFoundException", "ErrorMessage": "gone"},
            }
        ]

        with pytest.raises(RuntimeError, match="batch_update_partition failed for 1 partition"):
            gold._raise_on_batch_errors("batch_update_partition", errors)

    def test_the_batch_guard_is_silent_when_there_are_none(self, gold):
        assert gold._raise_on_batch_errors("batch_create_partition", []) is None

    def test_partitions_of_a_table_that_does_not_exist_are_empty_not_an_error(self, gold):
        """Reached when a table is dropped between the swap's own calls. Returning [] lets
        the promote finish rather than failing after the table has already been repointed."""
        assert gold._all_partitions("lottery_santalucia_db", "no_such_table") == []

    def test_rewriting_a_statement_without_a_create_raises(self, gold):
        with pytest.raises(ValueError, match="CREATE TABLE"):
            gold._rewrite_for_staging("SELECT 1", "db", "t__stg_x", "s3://b/p/")

    def test_rewriting_a_statement_without_a_location_raises(self, gold):
        """`prepare` validates both before calling this, so these two guards only fire for a
        future caller — which is exactly when a silent wrong-location write would hurt."""
        with pytest.raises(ValueError, match="external_location"):
            gold._rewrite_for_staging("CREATE TABLE db.t AS SELECT 1", "db", "t__stg_x", "s3://b/")


class TestTheInputsSentToGlue:
    """PR-031.3 — the swap must send Glue only fields Glue accepts.

    `_table_input` used to be a DENYLIST: take the whole GetTable response, subtract the
    keys known to be read-only, send the rest. That inverts the safety property. On
    2026-09-24 Glue started returning `IsMaterializedView`, it was on no list, and
    `update_table` rejected the call with `ParamValidationError` — PromoteGold failed on a
    run whose extraction, transform, crawlers, DQ gate and CTAS had all passed, and every
    future field AWS adds would have done the same.

    The regression test is `test_an_unknown_field_is_dropped`; the other two are the
    contract that keeps it true.
    """

    def test_an_unknown_field_is_dropped(self, gold):
        """The 2026-09-24 outage, reproduced by name.

        Not parameterised on the real field alone: any unrecognised key must be dropped,
        because the next one will have a different name and no warning.
        """
        staged = {
            "Name": "gold_draw_summary__stg_run",
            "StorageDescriptor": {"Location": "s3://b/p/"},
            "IsMaterializedView": False,
            "SomeFieldAwsHasNotInventedYet": {"nested": True},
        }

        payload = gold._table_input(staged, "gold_draw_summary")

        assert "IsMaterializedView" not in payload
        assert "SomeFieldAwsHasNotInventedYet" not in payload
        assert payload["Name"] == "gold_draw_summary"
        assert payload["StorageDescriptor"] == {"Location": "s3://b/p/"}

    def test_the_read_only_fields_are_still_dropped(self, gold):
        """The denylist's actual job, which the allowlist has to keep doing.

        `DatabaseName`, `CatalogId` and friends come back on every GetTable and are rejected
        by TableInput — the allowlist excludes them by not naming them, but that is worth an
        assertion rather than an inference.
        """
        staged = {
            "Name": "t__stg_run",
            "DatabaseName": "lottery_santalucia_db",
            "CatalogId": "913524903233",
            "CreateTime": "2026-09-24",
            "UpdateTime": "2026-09-24",
            "CreatedBy": "arn:aws:sts::913524903233:assumed-role/x",
            "IsRegisteredWithLakeFormation": True,
            "VersionId": "4",
            "Parameters": {"generation": "new"},
        }

        payload = gold._table_input(staged, "t")

        assert set(payload) == {"Name", "Parameters"}

    def test_every_field_we_send_is_one_glue_accepts(self, gold):
        """The guard that makes the fix self-maintaining.

        Checked against botocore's own service model — the same source that produced the
        error message in the outage — so this fails in CI if either allowlist ever names a
        field the API does not take. A subset, not an equality: a field AWS adds that we
        simply do not send cannot break anything, and should not turn CI red.

        `botocore.session` reads a bundled JSON model. No credentials, no network.
        """
        import botocore.session

        glue_model = botocore.session.get_session().get_service_model("glue")

        table_fields = set(glue_model.shape_for("TableInput").members)
        partition_fields = set(glue_model.shape_for("PartitionInput").members)

        assert gold._TABLE_INPUT_FIELDS <= table_fields, (
            "TableInput fields Glue does not accept: "
            f"{sorted(gold._TABLE_INPUT_FIELDS - table_fields)}"
        )
        assert gold._PARTITION_INPUT_FIELDS <= partition_fields, (
            "PartitionInput fields Glue does not accept: "
            f"{sorted(gold._PARTITION_INPUT_FIELDS - partition_fields)}"
        )

    def test_partition_input_keeps_carrying_what_it_carried(self, gold):
        """The partition path had the same denylist shape and the same latent bug.

        Narrowing it changed nothing that ships: `Values`, `StorageDescriptor` and
        `Parameters` are what the old subtraction left behind, and they are what it leaves
        behind now. The response keys around them are the ones that must not survive.
        """
        partition = {
            "Values": ["2026"],
            "StorageDescriptor": {"Location": "s3://b/p/year=2026/"},
            "Parameters": {"k": "v"},
            "DatabaseName": "lottery_santalucia_db",
            "TableName": "gold_draw_summary",
            "CreationTime": "2026-09-24",
            "CatalogId": "913524903233",
            "IsSomethingNew": True,
        }

        assert gold._partition_input(partition) == {
            "Values": ["2026"],
            "StorageDescriptor": {"Location": "s3://b/p/year=2026/"},
            "Parameters": {"k": "v"},
        }
