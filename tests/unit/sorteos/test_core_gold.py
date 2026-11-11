"""Gold in the cloud (UY-044.3): sorteos.core.gold.Builder and sorteos.uy.lambda_gold.

Athena, Glue and S3 are small fakes that keep state, so the tests can ask the questions that
matter after a run: what does the published table point at, what is left in S3, and what did a
failure leave behind.
"""

from __future__ import annotations

import ast
import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from sorteos.core import gold
from sorteos.uy import lambda_gold

REPO = Path(__file__).parents[3]
TARGET = gold.Target("lottery_uy_db", "lottery-uy-wg", "data-bucket", "uy/gold/")
QUERIES = {"gold_a": "SELECT 1 AS x", "gold_b": "WITH t AS (SELECT 2 AS y) SELECT y FROM t"}
G1, G2, G3, G4 = "20261110T023000Z", "20261111T023000Z", "20261112T023000Z", "20261113T023000Z"


class NotFound(Exception):
    pass


class FakeGlue:
    class exceptions:  # noqa: N801 - boto3's name
        EntityNotFoundException = NotFound

    def __init__(self):
        self.tables: dict[str, dict] = {}
        self.calls: list[tuple[str, str]] = []
        self.fail_update: str | None = None

    def get_table(self, DatabaseName, Name):  # noqa: N803
        if Name not in self.tables:
            raise NotFound(Name)
        # What GetTable adds and UpdateTable refuses.
        extra = {"DatabaseName": DatabaseName, "CreateTime": 1, "CatalogId": "1", "VersionId": "7"}
        return {"Table": {**self.tables[Name], **extra}}

    def update_table(self, DatabaseName, TableInput):  # noqa: N803
        self.calls.append(("update", TableInput["Name"]))
        if TableInput["Name"] == self.fail_update:
            raise RuntimeError("AccessDeniedException")
        if TableInput["Name"] not in self.tables:
            raise NotFound(TableInput["Name"])
        assert not {"CreateTime", "CatalogId", "VersionId", "DatabaseName"} & set(TableInput)
        self.tables[TableInput["Name"]] = TableInput

    def create_table(self, DatabaseName, TableInput):  # noqa: N803
        self.calls.append(("create", TableInput["Name"]))
        self.tables[TableInput["Name"]] = TableInput

    def delete_table(self, DatabaseName, Name):  # noqa: N803
        self.calls.append(("delete", Name))
        if Name not in self.tables:
            raise NotFound(Name)
        del self.tables[Name]


class _Pages:
    def __init__(self, fn):
        self.paginate = fn


class FakeS3:
    def __init__(self):
        self.versions: list[tuple[str, str]] = []  # (key, version id), delete markers included
        self.deny = False
        self.delete_calls = 0

    def put(self, key: str, versions: int = 1):
        for n in range(versions):
            self.versions.append((key, f"v{len(self.versions)}-{n}"))

    def keys(self) -> set[str]:
        return {k for k, _ in self.versions}

    def get_paginator(self, name):
        if name == "list_objects_v2":
            return _Pages(self._list)
        assert name == "list_object_versions"
        return _Pages(self._versions)

    def _list(self, Bucket, Prefix, Delimiter):  # noqa: N803
        folders = sorted(
            {
                Prefix + k[len(Prefix) :].split("/")[0] + "/"
                for k in self.keys()
                if k.startswith(Prefix)
            }
        )
        return [{"CommonPrefixes": [{"Prefix": f} for f in folders]}] if folders else [{}]

    def _versions(self, Bucket, Prefix):  # noqa: N803
        found = [{"Key": k, "VersionId": v} for k, v in self.versions if k.startswith(Prefix)]
        half = len(found) // 2
        return [{"Versions": found[:half]}, {"DeleteMarkers": found[half:]}]

    def delete_objects(self, Bucket, Delete):  # noqa: N803
        self.delete_calls += 1
        if self.deny:
            return {
                "Errors": [{"Key": o["Key"], "Code": "AccessDenied"} for o in Delete["Objects"]]
            }
        gone = {(o["Key"], o["VersionId"]) for o in Delete["Objects"]}
        self.versions = [v for v in self.versions if v not in gone]
        return {}


class FakeAthena:
    """A CTAS that succeeds writes one file at its location and registers the staging table."""

    def __init__(self, glue: FakeGlue, s3: FakeS3):
        self.glue, self.s3 = glue, s3
        self.sql: dict[str, str] = {}
        self.fail: dict[str, str] = {}  # table -> reason
        self.rows: dict[str, int] = {}  # staging name -> rows (default 5)
        self.never_finishes = False
        self.stopped: list[str] = []
        self.started_with: list[dict] = []

    def start_query_execution(self, QueryString, WorkGroup, QueryExecutionContext):  # noqa: N803
        query_id = f"q{len(self.sql)}"
        self.sql[query_id] = QueryString
        self.started_with.append({"WorkGroup": WorkGroup, **QueryExecutionContext})
        match = re.match(r'CREATE TABLE "(\w+)"\."(\w+)"', QueryString)
        if match and not self._failure(match.group(2)) and not self.never_finishes:
            location = re.search(r"external_location = '([^']+)'", QueryString).group(1)
            assert location.startswith("s3://data-bucket/") and location.endswith("/")
            self.s3.put(location[len("s3://data-bucket/") :] + "part-0.parquet")
            self.glue.tables[match.group(2)] = {
                "Name": match.group(2),
                "TableType": "EXTERNAL_TABLE",
                "Parameters": {"transient_lastDdlTime": "1", "auto.purge": "false"},
                "StorageDescriptor": {
                    "Columns": [{"Name": "x", "Type": "int"}],
                    "Location": location.rstrip("/"),
                    "InputFormat": "parquet.in",
                    "OutputFormat": "parquet.out",
                    "SerdeInfo": {"SerializationLibrary": "parquet.serde"},
                    "SomethingNew": "a field AWS adds one day",
                },
            }
        return {"QueryExecutionId": query_id}

    def _failure(self, staging: str) -> str | None:
        return next((why for table, why in self.fail.items() if f"stg_{table}_" in staging), None)

    def get_query_execution(self, QueryExecutionId):  # noqa: N803
        sql = self.sql[QueryExecutionId]
        match = re.match(r'CREATE TABLE "\w+"\."(\w+)"', sql)
        if self.never_finishes:
            return {"QueryExecution": {"Status": {"State": "RUNNING"}}}
        if match and self._failure(match.group(1)):
            status = {"State": "FAILED", "StateChangeReason": self._failure(match.group(1))}
            return {"QueryExecution": {"Status": status}}
        statistics = {"DataScannedInBytes": 1234, "EngineExecutionTimeInMillis": 900}
        return {"QueryExecution": {"Status": {"State": "SUCCEEDED"}, "Statistics": statistics}}

    def stop_query_execution(self, QueryExecutionId):  # noqa: N803
        self.stopped.append(QueryExecutionId)

    def get_query_results(self, QueryExecutionId):  # noqa: N803
        pairs = re.findall(
            r"SELECT '(\w+)' AS table_name.*?\"\.\"(\w+)\"", self.sql[QueryExecutionId]
        )
        rows = [{"Data": [{"VarCharValue": "table_name"}, {"VarCharValue": "row_count"}]}]
        for table, _staging in pairs:
            count = str(self.rows.get(table, 5))
            rows.append({"Data": [{"VarCharValue": table}, {"VarCharValue": count}]})
        return {"ResultSet": {"Rows": rows}}


class World:
    def __init__(self):
        self.glue, self.s3 = FakeGlue(), FakeS3()
        self.athena = FakeAthena(self.glue, self.s3)
        self.time = 0.0
        self.builder = gold.Builder(
            athena=self.athena,
            glue=self.glue,
            s3=self.s3,
            target=TARGET,
            sleep=self._sleep,
            clock=lambda: self.time,
        )

    def _sleep(self, seconds: float) -> None:
        self.time += seconds

    def run(self, generation: str, **kwargs) -> dict:
        return self.builder.run(
            QUERIES, run_id=f"exec-{generation}", generation=generation, **kwargs
        )

    def live(self, table: str) -> str:
        return gold.generation_of(self.glue.tables[table]["StorageDescriptor"]["Location"])

    def generations(self, table: str) -> set[str]:
        prefix = f"uy/gold/{table}/run="
        return {k[len(prefix) :].split("/")[0] for k in self.s3.keys() if k.startswith(prefix)}


@pytest.fixture
def world() -> World:
    return World()


# --- the pure parts --------------------------------------------------------------------------


def test_generation_is_a_utc_timestamp_that_sorts():
    assert gold.new_generation(datetime(2026, 11, 11, 2, 30, 5, tzinfo=UTC)) == "20261111T023005Z"
    assert gold.new_generation() > "20261111T000000Z"
    assert gold.staging_name("gold_a", G1) == "stg_gold_a_20261110t023000z"
    assert TARGET.location("gold_a", G1) == f"s3://data-bucket/uy/gold/gold_a/run={G1}/"


def test_generation_of_reads_only_our_locations():
    assert gold.generation_of(f"s3://b/uy/gold/gold_a/run={G1}/") == G1
    assert gold.generation_of(f"s3://b/uy/gold/gold_a/run={G1}") == G1
    assert gold.generation_of("s3://b/uy/gold/gold_a/") is None
    assert gold.generation_of("s3://b/uy/gold/gold_a/run=manual-test/") is None


def test_ctas_keeps_the_select_as_written():
    sql = gold.ctas("SELECT 1 AS x", "db", "stg_gold_a_1", "s3://b/p/")
    assert sql.startswith('CREATE TABLE "db"."stg_gold_a_1"\nWITH (')
    assert "format = 'PARQUET'" in sql and "external_location = 's3://b/p/'" in sql
    assert sql.endswith("\nAS\nSELECT 1 AS x")


@pytest.mark.parametrize(
    ("generations", "keep", "doomed"),
    [
        ([G1], [G1], []),
        ([G1, G2], [G2, G1], []),
        ([G1, G2, G3], [G3, G2], [G1]),
        ([G1, G2, G3], [G3], [G1, G2]),
        # G2 was written by a run that failed: older than the live one, and never published.
        ([G1, G2, G3], [G3, G1], [G2]),
        ([G1, G2, G3, G4], [G2, G1], [G3, G4]),
    ],
)
def test_to_retire(generations, keep, doomed):
    assert gold.to_retire(generations, keep) == doomed


def test_to_retire_refuses_when_the_live_generation_is_not_in_s3():
    with pytest.raises(gold.GoldError, match="not in S3"):
        gold.to_retire([G1], [G2, G1])
    with pytest.raises(gold.GoldError, match="not in S3"):
        gold.to_retire([G1], [])


def test_target_prefix_must_be_a_folder():
    for bad in ("uy/gold", "/uy/gold/"):
        with pytest.raises(gold.GoldError):
            gold.Target("db", "wg", "b", bad)


def test_load_queries(tmp_path):
    (tmp_path / "02_gold_b.sql").write_text("SELECT 2;\n", "utf-8")
    (tmp_path / "01_gold_a.sql").write_text("-- why\nSELECT 1\n", "utf-8")
    assert gold.load_queries(tmp_path) == {"gold_a": "-- why\nSELECT 1", "gold_b": "SELECT 2"}
    (tmp_path / "notes.sql").write_text("SELECT 3", "utf-8")
    with pytest.raises(gold.GoldError, match="expected NN_gold"):
        gold.load_queries(tmp_path)


def test_the_real_queries_load():
    assert len(gold.load_queries(REPO / "sql" / "uy" / "gold")) == 6


# --- a run -----------------------------------------------------------------------------------


def test_first_run_creates_the_tables_on_their_generation(world):
    report = world.run(G1)
    assert report["ok"] is True and report["swapped"] == ["gold_a", "gold_b"]
    assert set(world.glue.tables) == {"gold_a", "gold_b"}  # the staging entries are gone
    for table in QUERIES:
        published = world.glue.tables[table]
        assert (
            published["StorageDescriptor"]["Location"]
            == f"s3://data-bucket/uy/gold/{table}/run={G1}"
        )
        assert published["Parameters"] == {
            "EXTERNAL": "TRUE",
            "classification": "parquet",
            "gold.generation": G1,
            "gold.run_id": f"exec-{G1}",
            "gold.previous_generations": "",
        }
        # Only allowlisted fields travel from the staging table (PR-042.3).
        assert "SomethingNew" not in published["StorageDescriptor"]
        assert published["StorageDescriptor"]["Columns"] == [{"Name": "x", "Type": "int"}]
        assert report["tables"][table] == {
            "rows": 5,
            "location": f"s3://data-bucket/uy/gold/{table}/run={G1}/",
            "scanned_bytes": 1234,
            "athena_ms": 900,
        }
    assert report["retired"] == {"gold_a": {}, "gold_b": {}}
    assert world.s3.delete_calls == 0  # a first run deletes nothing
    assert all(
        s == {"WorkGroup": "lottery-uy-wg", "Database": "lottery_uy_db"}
        for s in world.athena.started_with
    )


def test_later_runs_update_in_place_and_keep_one_generation_to_roll_back_to(world):
    world.run(G1)
    world.run(G2)
    assert world.live("gold_a") == G2 and world.generations("gold_a") == {G1, G2}
    assert ("update", "gold_a") in world.glue.calls
    report = world.run(G3)
    assert report["retired"] == {"gold_a": {G1: 1}, "gold_b": {G1: 1}}
    for table in QUERIES:
        assert world.live(table) == G3
        assert world.generations(table) == {G2, G3}


def test_retire_deletes_every_version_and_delete_marker(world):
    world.run(G1)
    world.s3.put(f"uy/gold/gold_a/run={G1}/part-0.parquet", versions=4)  # 5 versions now
    world.s3.put("uy/gold/gold_a/README.txt")  # not a generation: never touched
    world.s3.put("uy/silver/draws/part-0.parquet")
    world.run(G2)
    report = world.run(G3)
    assert report["retired"]["gold_a"] == {G1: 5}
    assert not [k for k in world.s3.keys() if f"run={G1}" in k]
    assert {"uy/gold/gold_a/README.txt", "uy/silver/draws/part-0.parquet"} <= world.s3.keys()


def test_a_failed_ctas_publishes_nothing_and_drops_its_staging(world):
    world.run(G1)
    world.athena.fail = {"gold_b": "SYNTAX_ERROR: line 3"}
    with pytest.raises(gold.GoldError, match="SYNTAX_ERROR"):
        world.run(G2)
    assert set(world.glue.tables) == {"gold_a", "gold_b"}
    assert (
        world.live("gold_a") == G1 and world.live("gold_b") == G1
    )  # gold_a was built, not swapped
    assert world.s3.delete_calls == 0
    # The bytes gold_a wrote stay until the next good run, which sees them as newer than live.
    assert world.generations("gold_a") == {G1, G2}
    world.athena.fail = {}
    report = world.run(G3)
    assert report["retired"]["gold_a"] == {G2: 1}
    assert world.generations("gold_a") == {G1, G3} and world.live("gold_a") == G3


def test_an_empty_table_stops_the_swap_of_all(world):
    world.run(G1)
    world.athena.rows = {"gold_b": 0}
    with pytest.raises(gold.GoldError, match=r"no rows.*gold_b"):
        world.run(G2)
    assert world.live("gold_a") == G1 and world.live("gold_b") == G1
    assert set(world.glue.tables) == {"gold_a", "gold_b"}


def test_a_swap_that_fails_midway_says_which_tables_moved(world):
    world.run(G1)
    world.glue.fail_update = "gold_b"
    with pytest.raises(gold.GoldError, match=r"swap stopped at gold_b.*\['gold_a'\]"):
        world.run(G2)
    assert world.live("gold_a") == G2 and world.live("gold_b") == G1
    world.glue.fail_update = None
    world.run(G3)  # a full run puts both on one generation again
    assert world.live("gold_a") == G3 and world.live("gold_b") == G3


def test_a_refused_delete_fails_the_run_after_the_swap(world):
    """The bucket's Deny before the owner adds the exemption: loud, and gold is already right."""
    world.run(G1)
    world.run(G2)
    world.s3.deny = True
    with pytest.raises(gold.GoldError, match="S3 refused to delete .*AccessDenied"):
        world.run(G3)
    assert world.live("gold_a") == G3
    assert world.generations("gold_a") == {G1, G2, G3}
    world.s3.deny = False
    world.run(G4)
    assert world.generations("gold_a") == {G3, G4}


def test_athena_that_never_answers_is_stopped(world):
    world.athena.never_finishes = True
    with pytest.raises(gold.GoldError, match="did not finish in 150 s"):
        world.run(G1)
    assert sorted(world.athena.stopped) == ["q0", "q1"]
    assert world.glue.tables == {}


def test_bad_inputs(world):
    with pytest.raises(gold.GoldError, match="no gold queries"):
        world.builder.run({}, run_id="x")
    with pytest.raises(gold.GoldError, match="bad generation"):
        world.builder.run(QUERIES, run_id="x", generation="tonight")
    with pytest.raises(gold.GoldError, match="refusing to delete"):
        world.builder._delete_generation("gold_a", "../../silver")
    with pytest.raises(gold.GoldError, match="nothing says which generation is live"):
        world.builder.retire("gold_a")
    world.glue.tables["gold_a"] = {
        "StorageDescriptor": {"Location": "s3://data-bucket/uy/gold/gold_a/"}
    }
    with pytest.raises(gold.GoldError, match="not published on a generation"):
        world.builder.retire("gold_a")


def test_a_count_that_names_other_tables_is_an_error(world, monkeypatch):
    answer = {"ResultSet": {"Rows": [{"Data": []}]}}
    monkeypatch.setattr(world.athena, "get_query_results", lambda QueryExecutionId: answer)  # noqa: N803
    with pytest.raises(gold.GoldError, match="counted"):
        world.run(G1)


# --- the Lambda ------------------------------------------------------------------------------


@pytest.fixture
def env(monkeypatch):
    for name, value in {
        "GOLD_DATABASE": "lottery_uy_db",
        "GOLD_WORKGROUP": "lottery-uy-wg",
        "GOLD_BUCKET": "data-bucket",
        "GOLD_PREFIX": "uy/gold/",
    }.items():
        monkeypatch.setenv(name, value)


def test_handler_builds_the_six_tables(world, env):
    clients = {"athena": world.athena, "glue": world.glue, "s3": world.s3}
    report = lambda_gold.handler({"run_id": "exec-1", "dry_run": False}, clients=clients)
    assert report["ok"] is True and len(report["swapped"]) == 6
    assert report["run_id"] == "exec-1"
    json.dumps(report)  # Step Functions keeps it as the state's output
    assert sorted(world.glue.tables) == sorted(gold.load_queries(REPO / "sql" / "uy" / "gold"))


@pytest.mark.parametrize(
    "event", [{"run_id": "x", "dry_run": True}, {"run_id": "x", "dry_run": "false"}]
)
def test_handler_refuses_a_dry_run(world, env, event):
    with pytest.raises(gold.GoldError, match="no dry run"):
        lambda_gold.handler(
            event, clients={"athena": world.athena, "glue": world.glue, "s3": world.s3}
        )
    assert world.athena.sql == {}


@pytest.mark.parametrize("event", [None, {}, {"run_id": ""}, {"run_id": 7}])
def test_handler_needs_a_run_id(world, env, event):
    with pytest.raises(gold.GoldError, match="run_id"):
        lambda_gold.handler(event, clients={})


def test_sql_dir(monkeypatch, tmp_path):
    assert lambda_gold.sql_dir() == REPO / "sql" / "uy" / "gold"
    monkeypatch.setenv("GOLD_SQL_DIR", str(tmp_path))
    assert lambda_gold.sql_dir() == tmp_path


def test_handler_makes_its_own_clients(env, monkeypatch):
    import boto3

    made = []
    monkeypatch.setattr(boto3, "client", lambda name: made.append(name) or object())
    monkeypatch.setattr(
        gold.Builder, "run", lambda self, queries, **kw: {"ok": True, "n": len(queries)}
    )
    assert lambda_gold.handler({"run_id": "x"}) == {"ok": True, "n": 6}
    assert made == ["athena", "glue", "s3"]


# --- the zip ---------------------------------------------------------------------------------


def test_the_zip_holds_everything_the_handler_imports():
    """gold.tf lists the files by hand; nothing in them may need a file that is not listed."""
    text = (REPO / "terraform" / "uy" / "gold.tf").read_text("utf-8")
    listed = set(re.findall(r'"(sorteos/[\w/]+\.py)"\s*=', text))
    assert listed == {
        "sorteos/__init__.py",
        "sorteos/core/__init__.py",
        "sorteos/core/gold.py",
        "sorteos/uy/__init__.py",
        "sorteos/uy/lambda_gold.py",
    }
    assert 'fileset("${path.module}/../../sql/uy/gold", "*.sql")' in text
    allowed = {"sorteos", "sorteos.core", "sorteos.core.gold", "boto3", "__future__"}
    import sys

    for name in listed:
        tree = ast.parse((REPO / "src" / name).read_text("utf-8"))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            for imported in names:
                top = imported.split(".")[0]
                assert imported in allowed or top in sys.stdlib_module_names, (name, imported)
