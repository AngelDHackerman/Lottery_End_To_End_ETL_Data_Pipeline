"""Gold: build every table beside the published one, then swap them all (UY-044.3; D33).

A gold table is one SELECT over silver (``sql/<country>/gold/NN_gold_<name>.sql``). One run:

1. **Build.** Every SELECT runs as an Athena CTAS into a staging table at a new location,
   ``<prefix><table>/run=<generation>/``. Nothing published is touched: until step 3 a reader
   sees last night's gold, whole.
2. **Check.** Every staging table must have rows. A swap onto an empty table succeeds, and
   nobody notices until someone counts (master's PR-042 lesson).
3. **Swap**, only if every table passed: each published table is pointed at its new location
   with one ``UpdateTable`` (or created, the first time). The tables are swapped one after the
   other, milliseconds apart; a failure midway is reported with the tables already swapped, and
   the next run puts all of them on one generation again.
4. **Retire.** Per table, keep the live generation and the ``keep_previous`` that were
   published before it (the rollback target; the table itself remembers them) and delete the
   rest, among them what a failed run left written. The bucket is versioned, so every version
   goes, or nothing is freed.

Why one process and not a state per table, as Santa Lucía does (owner, UY-044.3 1a): with a
state per table, five tables can be promoted and the sixth fail, and gold then mixes two
nights. Here the swap starts only when all are built and counted.

A generation is a UTC timestamp made here, never the execution's name: a retried execution
gets a new one, so a CTAS never meets its own half-written folder (Athena refuses a location
that is not empty), and generations sort by name.

Knows no country and reads no file but the SQL: the clients are passed in, so the tests run it
without AWS. Only the standard library is imported, so the Lambda's zip needs nothing else.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_FILE_RE = re.compile(r"^\d{2}_(gold_[a-z0-9_]+)\.sql$")
_TABLE_RE = re.compile(r"^gold_[a-z0-9_]+$")
_GENERATION_RE = re.compile(r"^\d{8}T\d{6}Z$")
_RUN_PREFIX = "run="
_PREVIOUS = "gold.previous_generations"
# What a published table takes from the staging one. An allowlist (PR-042.3): GetTable returns
# fields UpdateTable refuses (CreateTime, CatalogId, VersionId...), and a denylist breaks the
# day AWS adds one.
_STORAGE_KEYS = (
    "Columns",
    "Location",
    "InputFormat",
    "OutputFormat",
    "Compressed",
    "NumberOfBuckets",
    "SerdeInfo",
    "BucketColumns",
    "SortColumns",
    "Parameters",
    "StoredAsSubDirectories",
)
_DONE = frozenset({"SUCCEEDED", "FAILED", "CANCELLED"})


class GoldError(RuntimeError):
    pass


@dataclass(frozen=True)
class Target:
    database: str
    workgroup: str
    bucket: str
    prefix: str  # "uy/gold/": ends with a slash

    def __post_init__(self) -> None:
        if not self.prefix.endswith("/") or self.prefix.startswith("/"):
            raise GoldError(f"prefix must look like 'uy/gold/', got {self.prefix!r}")

    def table_prefix(self, table: str) -> str:
        return f"{self.prefix}{table}/"

    def generation_prefix(self, table: str, generation: str) -> str:
        return f"{self.table_prefix(table)}{_RUN_PREFIX}{generation}/"

    def location(self, table: str, generation: str) -> str:
        return f"s3://{self.bucket}/{self.generation_prefix(table, generation)}"


def load_queries(sql_dir: Path) -> dict[str, str]:
    """{table: SELECT}, in file order. A file that is not NN_gold_<name>.sql is an error."""
    found: dict[str, str] = {}
    for path in sorted(Path(sql_dir).glob("*.sql")):
        match = _FILE_RE.match(path.name)
        if not match:
            raise GoldError(f"{path.name}: expected NN_gold_<name>.sql")
        text = path.read_text("utf-8").strip().rstrip(";").strip()
        if not text:
            raise GoldError(f"{path.name} is empty")
        found[match.group(1)] = text
    if not found:
        raise GoldError(f"no SQL files in {sql_dir}")
    return found


def new_generation(now: datetime | None = None) -> str:
    return (now or datetime.now(UTC)).astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def staging_name(table: str, generation: str) -> str:
    return f"stg_{table}_{generation.lower()}"


def ctas(select: str, database: str, staging: str, location: str) -> str:
    """The SELECT of the file, as it is, written as Parquet to `location`."""
    return (
        f'CREATE TABLE "{database}"."{staging}"\n'
        f"WITH (format = 'PARQUET', write_compression = 'SNAPPY', "
        f"external_location = '{location}')\nAS\n{select}"
    )


def generation_of(location: str) -> str | None:
    """The generation a table location points at, or None if it is not one of ours."""
    last = location.rstrip("/").rsplit("/", 1)[-1]
    if not last.startswith(_RUN_PREFIX):
        return None
    generation = last[len(_RUN_PREFIX) :]
    return generation if _GENERATION_RE.match(generation) else None


def to_retire(generations: list[str], keep: list[str]) -> list[str]:
    """Every generation in S3 that is not one of `keep` (the live one first)."""
    if not keep or keep[0] not in generations:
        raise GoldError(f"the live generation {keep[:1]} is not in S3: {sorted(generations)}")
    return sorted(g for g in generations if g not in keep)


class Builder:
    def __init__(
        self,
        *,
        athena: Any,
        glue: Any,
        s3: Any,
        target: Target,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        poll_seconds: float = 1.0,
        timeout_seconds: float = 150.0,
    ) -> None:
        self.athena, self.glue, self.s3 = athena, glue, s3
        self.target = target
        self._sleep, self._clock = sleep, clock
        self._poll, self._timeout = poll_seconds, timeout_seconds

    # --- Athena ---------------------------------------------------------------------------

    def _start(self, sql: str) -> str:
        return self.athena.start_query_execution(
            QueryString=sql,
            WorkGroup=self.target.workgroup,
            QueryExecutionContext={"Database": self.target.database},
        )["QueryExecutionId"]

    def _wait(self, ids: Mapping[str, str]) -> dict[str, dict]:
        """Wait for every query. Returns {name: QueryExecution}; raises on the first that failed."""
        deadline = self._clock() + self._timeout
        done: dict[str, dict] = {}
        while len(done) < len(ids):
            for name, query_id in ids.items():
                if name in done:
                    continue
                execution = self.athena.get_query_execution(QueryExecutionId=query_id)[
                    "QueryExecution"
                ]
                if execution["Status"]["State"] in _DONE:
                    done[name] = execution
            if len(done) < len(ids):
                if self._clock() >= deadline:
                    pending = sorted(set(ids) - set(done))
                    for name in pending:
                        self.athena.stop_query_execution(QueryExecutionId=ids[name])
                    raise GoldError(f"Athena did not finish in {self._timeout:.0f} s: {pending}")
                self._sleep(self._poll)
        failed = {
            name: e["Status"].get("StateChangeReason", e["Status"]["State"])
            for name, e in done.items()
            if e["Status"]["State"] != "SUCCEEDED"
        }
        if failed:
            raise GoldError(f"Athena failed: {failed}")
        return done

    def _counts(self, staging: Mapping[str, str]) -> dict[str, int]:
        # Not user input: run() only lets through table names that are gold_<a-z0-9_>, and the
        # staging names are built from them and a timestamp.
        sql = "\nUNION ALL\n".join(  # nosec B608
            f"SELECT '{table}' AS table_name, count(*) AS row_count "  # noqa: S608
            f'FROM "{self.target.database}"."{name}"'  # nosec B608
            for table, name in staging.items()
        )
        query_id = self._start(sql)
        self._wait({"count": query_id})
        rows = self.athena.get_query_results(QueryExecutionId=query_id)["ResultSet"]["Rows"]
        counts = {r["Data"][0]["VarCharValue"]: int(r["Data"][1]["VarCharValue"]) for r in rows[1:]}
        if set(counts) != set(staging):
            raise GoldError(f"counted {sorted(counts)}, built {sorted(staging)}")
        return counts

    # --- the catalog ----------------------------------------------------------------------

    def _published(self, table: str) -> list[str]:
        """The generations the catalog vouches for: the live one, then the ones before it.

        Empty if the table does not exist. The history is kept in the table itself
        (`gold.previous_generations`) and not read from S3 by date: a run that failed after
        writing leaves a folder newer than the live one and, once the next run succeeds, older
        than it. Only a generation that was once published is a rollback target.
        """
        try:
            found = self.glue.get_table(DatabaseName=self.target.database, Name=table)["Table"]
        except self.glue.exceptions.EntityNotFoundException:
            return []
        location = found["StorageDescriptor"]["Location"]
        live = generation_of(location)
        if live is None:
            raise GoldError(f"{table} is not published on a generation: {location!r}")
        previous = found.get("Parameters", {}).get(_PREVIOUS, "")
        return [live, *[g for g in previous.split(",") if _GENERATION_RE.match(g)]]

    def _swap(
        self, table: str, staging: str, generation: str, run_id: str, keep_previous: int
    ) -> None:
        built = self.glue.get_table(DatabaseName=self.target.database, Name=staging)["Table"]
        descriptor = built["StorageDescriptor"]
        published = self._published(table)
        table_input = {
            "Name": table,
            "Description": f"Gold: the SELECT of *_{table}.sql over silver. Swapped whole.",
            "TableType": "EXTERNAL_TABLE",
            "PartitionKeys": [],
            "Parameters": {
                "EXTERNAL": "TRUE",
                "classification": "parquet",
                "gold.generation": generation,
                "gold.run_id": run_id,
                _PREVIOUS: ",".join(published[:keep_previous]),
            },
            "StorageDescriptor": {k: descriptor[k] for k in _STORAGE_KEYS if k in descriptor},
        }
        if published:
            self.glue.update_table(DatabaseName=self.target.database, TableInput=table_input)
        else:
            self.glue.create_table(DatabaseName=self.target.database, TableInput=table_input)

    def _drop_staging(self, names: list[str]) -> None:
        for name in names:
            try:
                self.glue.delete_table(DatabaseName=self.target.database, Name=name)
            except self.glue.exceptions.EntityNotFoundException:
                pass

    # --- S3 -------------------------------------------------------------------------------

    def _generations(self, table: str) -> list[str]:
        prefix = self.target.table_prefix(table)
        found: list[str] = []
        pages = self.s3.get_paginator("list_objects_v2").paginate(
            Bucket=self.target.bucket, Prefix=prefix, Delimiter="/"
        )
        for page in pages:
            for common in page.get("CommonPrefixes", []):
                generation = generation_of(common["Prefix"])
                if generation:
                    found.append(generation)
        return found

    def _delete_generation(self, table: str, generation: str) -> int:
        """Every version and delete marker under one generation. Returns how many went."""
        prefix = self.target.generation_prefix(table, generation)
        # The guard that matters: this role may delete under <prefix> and nowhere else, and
        # this function only ever under one run= folder of one table.
        if not _GENERATION_RE.match(generation) or not prefix.startswith(self.target.prefix):
            raise GoldError(f"refusing to delete {prefix!r}")
        deleted = 0
        pages = self.s3.get_paginator("list_object_versions").paginate(
            Bucket=self.target.bucket, Prefix=prefix
        )
        for page in pages:
            objects = [
                {"Key": v["Key"], "VersionId": v["VersionId"]}
                for v in [*page.get("Versions", []), *page.get("DeleteMarkers", [])]
            ]
            for start in range(0, len(objects), 1000):
                batch = objects[start : start + 1000]
                answer = self.s3.delete_objects(
                    Bucket=self.target.bucket, Delete={"Objects": batch, "Quiet": True}
                )
                if answer.get("Errors"):
                    first = answer["Errors"][0]
                    raise GoldError(
                        f"S3 refused to delete {first.get('Key')}: {first.get('Code')} "
                        f"({len(answer['Errors'])} of {len(batch)})"
                    )
                deleted += len(batch)
        return deleted

    def retire(self, table: str) -> dict[str, int]:
        """Delete every generation the catalog does not vouch for. Returns {generation: objects}."""
        keep = self._published(table)
        if not keep:
            raise GoldError(f"{table} is not published: nothing says which generation is live")
        doomed = to_retire(self._generations(table), keep)
        return {generation: self._delete_generation(table, generation) for generation in doomed}

    # --- one run --------------------------------------------------------------------------

    def run(
        self,
        queries: Mapping[str, str],
        *,
        run_id: str,
        generation: str | None = None,
        keep_previous: int = 1,
    ) -> dict:
        if not queries:
            raise GoldError("no gold queries")
        bad = sorted(table for table in queries if not _TABLE_RE.match(table))
        if bad:
            raise GoldError(f"not gold table names: {bad}")
        generation = generation or new_generation()
        if not _GENERATION_RE.match(generation):
            raise GoldError(f"bad generation {generation!r}")
        target = self.target
        staging = {table: staging_name(table, generation) for table in queries}
        report: dict[str, Any] = {"generation": generation, "run_id": run_id, "tables": {}}

        # 1. build, 2. check. On any failure nothing published has changed: drop what was
        # staged in the catalog and leave. Its bytes were never published, so the next good
        # run retires them.
        try:
            ids = {
                table: self._start(
                    ctas(
                        select, target.database, staging[table], target.location(table, generation)
                    )
                )
                for table, select in queries.items()
            }
            executions = self._wait(ids)
            counts = self._counts(staging)
            empty = sorted(table for table, count in counts.items() if count == 0)
            if empty:
                raise GoldError(f"built with no rows, not publishing anything: {empty}")
        except Exception:
            logger.exception("gold build failed; published tables untouched")
            self._drop_staging(list(staging.values()))
            raise

        for table in queries:
            statistics = executions[table].get("Statistics", {})
            report["tables"][table] = {
                "rows": counts[table],
                "location": target.location(table, generation),
                "scanned_bytes": statistics.get("DataScannedInBytes"),
                "athena_ms": statistics.get("EngineExecutionTimeInMillis"),
            }

        # 3. swap, all of them, in file order.
        swapped: list[str] = []
        try:
            for table in queries:
                self._swap(table, staging[table], generation, run_id, keep_previous)
                swapped.append(table)
        except Exception as error:
            raise GoldError(
                f"swap stopped at {list(queries)[len(swapped)]}: {error}. Already on "
                f"{generation}: {swapped}. Run it again: a full run puts every table on one "
                "generation."
            ) from error
        self._drop_staging(list(staging.values()))
        report["swapped"] = swapped

        # 4. retire. A failure here fails the run, after the swap: gold is published and
        # right, and what failed is the cleanup, which must not pile up in silence.
        report["retired"] = {table: self.retire(table) for table in queries}
        report["ok"] = True
        return report
