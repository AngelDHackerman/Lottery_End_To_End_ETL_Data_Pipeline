"""Build each Gold table beside the live one, then swap the catalog onto it (PR-042.1).

**What this used to do, and why it was fault B.** The Lambda ran ``DROP TABLE`` *and*
hard-emptied the table's S3 prefix, then handed the ``CREATE TABLE ... AS SELECT`` back to
Step Functions. Between those two moments the table **did not exist** — not "held stale
data", did not exist. Athena CTAS is not transactional and the DROP had already happened, so
an Athena timeout, a workgroup limit or one bad Silver row took that gold table *and last
week's copy of it* until the next Thursday. Seven days of absence for one failed query, and
because ``BuildGold`` is a Map with concurrency 3, a partial failure left Gold internally
inconsistent with no single state to reason about.

**What it does now.** Two actions, one per Step Functions state:

``prepare``
    Rewrite the file's CREATE statement to build a **staging table** at a **staging
    location** — ``gold/<name>/run=<execution>/`` — and return it. Nothing is dropped and no
    published byte is touched. A failed CTAS now changes precisely nothing.

``promote``
    Called only after the CTAS succeeded. Point the published table at what was just built,
    through ``UpdateTable`` — one API call, atomic — and move its partitions across. The
    previous generation stays in S3, serving reads until the instant of the swap and
    available as a rollback afterwards. Retiring old generations is PR-042.2, deliberately
    separate: a delete that runs before the swap is the defect this PR exists to remove.

**The purge did not disappear, it moved.** ``_empty_prefix`` still runs in ``prepare``, but
against the staging location only — a prefix this execution owns and that has never been
published. It is there because Athena CTAS refuses a non-empty ``external_location``
(``HIVE_PATH_ALREADY_EXISTS``), and a retried execution would otherwise trip over its own
failed attempt.

**⚠️ The one transient, and it only happens once.** Before this PR the published tables point
at ``gold/<name>/`` — the *parent* of the new staging locations. Athena reads a location
recursively, so between the first CTAS finishing and its promote, a query against the old
table would see the old files *and* the new ``run=`` files, and double-count. The window is
seconds, it closes at promote, it never recurs (afterwards the table points at a specific
generation), and Gold has no consumer today — which the roadmap names as exactly why fault B
is cheap to fix now. The alternative, staging outside the table's own prefix, buys that one
transient at the cost of a layout where a table's data does not live under the table's
prefix. Recorded here rather than silently chosen.

The table name, target location and CREATE statement are still parsed from the SQL file, so
the file stays the single source of truth (no duplicated config in Terraform).
"""

from __future__ import annotations

import logging
import os
import re

import boto3

logger = logging.getLogger("loteria.gold.purge_and_load")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

_EXTERNAL_LOCATION_RE = re.compile(
    r"external_location\s*=\s*'s3://(?P<bucket>[^/]+)/(?P<prefix>.*?)'",
    re.IGNORECASE,
)
_CREATE_TABLE_RE = re.compile(
    r"CREATE\s+TABLE\s+(?P<db>[A-Za-z0-9_]+)\.(?P<table>[A-Za-z0-9_]+)",
    re.IGNORECASE,
)

s3 = boto3.client("s3")
glue = boto3.client("glue")


def _extract_create_statement(sql: str) -> str:
    """Return just the CREATE TABLE ... statement (drop the leading DROP + comments).

    Athena's StartQueryExecution accepts a single statement with no trailing semicolon.
    """
    match = _CREATE_TABLE_RE.search(sql)
    if not match:
        raise ValueError("No 'CREATE TABLE <db>.<table>' found in SQL file.")
    statement = sql[match.start() :]
    return statement.strip().rstrip(";").strip()


def _empty_prefix(bucket: str, prefix: str) -> int:
    """Permanently delete every version + delete-marker under s3://bucket/prefix.

    The bucket has versioning on (PR-002/005), so a plain delete would only add
    delete-markers and leave the underlying objects — and Athena CTAS then still fails
    with HIVE_PATH_ALREADY_EXISTS at a location that "looks" empty. Gold is derived,
    reproducible data (rebuilt from silver each run), so hard-deleting its versions is
    safe and keeps the location physically empty for the CTAS.

    Raises RuntimeError if S3 refuses any delete (e.g. the PR-002 bucket Deny policy), so
    a blocked purge fails loudly here instead of silently under-deleting and letting the
    downstream CTAS hit a non-empty location. Idempotent: an already-empty prefix
    deletes nothing and returns 0.
    """
    paginator = s3.get_paginator("list_object_versions")
    deleted = 0
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        targets = [
            {"Key": o["Key"], "VersionId": o["VersionId"]}
            for o in page.get("Versions", []) + page.get("DeleteMarkers", [])
        ]
        # delete_objects caps at 1000 entries per call; list_object_versions pages at
        # 1000 combined, so one delete call per page stays within the limit.
        for start in range(0, len(targets), 1000):
            batch = targets[start : start + 1000]
            if not batch:
                continue
            resp = s3.delete_objects(Bucket=bucket, Delete={"Objects": batch, "Quiet": True})
            errors = resp.get("Errors", [])
            if errors:
                first = errors[0]
                raise RuntimeError(
                    f"Failed to delete {len(errors)} object version(s) under "
                    f"s3://{bucket}/{prefix}: {first.get('Code')} {first.get('Message')} "
                    f"(key={first.get('Key')})"
                )
            deleted += len(batch)
    return deleted


def _drop_table(database: str, table: str) -> bool:
    """Drop the Glue catalog entry if it exists. Returns True if a table was removed.

    Mirrors ``DROP TABLE IF EXISTS`` — a missing table is not an error. Only ``promote``
    calls this now, and only against the staging entry: the published table is never
    dropped, it is updated in place.
    """
    try:
        glue.delete_table(DatabaseName=database, Name=table)
        return True
    except glue.exceptions.EntityNotFoundException:
        return False


# ==========================================================================================
# Staging identity
# ==========================================================================================
#: Separates the published table name from the run that built it. Double underscore so the
#: staging entries sort next to their table in the console and are greppable as a class.
STAGING_SUFFIX = "__stg_"

#: Execution names are two UUIDs joined by an underscore (~73 chars). Glue allows 255, so
#: this cap is for legibility in the console and in S3, not for the limit — and it keeps the
#: leading UUID, which is what ties a prefix back to an execution.
MAX_RUN_ID = 60


def _run_slug(run_id: str) -> str:
    """A run identifier safe for a Glue table name and an S3 prefix.

    Glue table names allow lowercase alphanumerics and underscores; Step Functions execution
    names also carry hyphens, and a manual run may carry anything a human typed.
    """
    slug = re.sub(r"[^a-z0-9]+", "_", run_id.lower()).strip("_")
    return (slug[:MAX_RUN_ID] or "manual").rstrip("_")


def _staging_identity(table: str, prefix: str, run_id: str) -> tuple[str, str]:
    """Return ``(staging_table, staging_prefix)`` for this run.

    The prefix is a CHILD of the published one on purpose — see the module docstring's note
    on the one-time transient. It keeps every generation of a table under that table's own
    prefix, which is what makes the lifecycle rule in PR-042.2 a one-liner.
    """
    slug = _run_slug(run_id)
    return f"{table}{STAGING_SUFFIX}{slug}", f"{prefix.rstrip('/')}/run={slug}/"


def _rewrite_for_staging(create_stmt: str, database: str, staging_table: str, location: str) -> str:
    """Point a CREATE TABLE AS SELECT at the staging table and the staging location.

    Both substitutions are positional — the regex match is replaced where it was found —
    rather than a string replace of the table name. The SELECT body mentions silver tables
    and the header carries comments; a blind replace would be free to corrupt either.
    """
    match = _CREATE_TABLE_RE.search(create_stmt)
    if not match:
        raise ValueError("No 'CREATE TABLE <db>.<table>' found in the CREATE statement.")
    stmt = (
        create_stmt[: match.start()]
        + f"CREATE TABLE {database}.{staging_table}"
        + create_stmt[match.end() :]
    )

    loc = _EXTERNAL_LOCATION_RE.search(stmt)
    if not loc:
        raise ValueError("No external_location found in the CREATE statement.")
    return stmt[: loc.start()] + f"external_location = '{location}'" + stmt[loc.end() :]


# ==========================================================================================
# The swap
# ==========================================================================================
#: Glue's own batch caps. Exceeding either is an InvalidInputException, not a partial write.
_BATCH_UPDATE = 100
_BATCH_CREATE = 100
_BATCH_DELETE = 25

#: The fields ``TableInput`` accepts. Anything else GetTable returns is dropped.
#:
#: PR-031.3: this was a DENYLIST, and its own comment argued for it — "a field added to a
#: future Glue API version keeps flowing through instead of being dropped" was written as
#: the feature. It is the bug. On 2026-09-24 Glue's GetTable response began carrying
#: ``IsMaterializedView``; nothing here knew to remove it, ``update_table`` rejected it with
#: ``ParamValidationError``, and PromoteGold failed on a run whose extraction, transform,
#: crawlers, DQ gate and CTAS had all succeeded. Every field AWS adds from here on was
#: another scheduled outage.
#:
#: Written by hand rather than read from ``glue.meta.service_model`` so the accepted set is
#: reviewable in the diff and identical in every runtime. ``test_table_input_fields_are_all_
#: accepted_by_glue`` asserts it stays a subset of botocore's TableInput shape, which is the
#: property that actually prevents the outage: a field we never send cannot be rejected.
#:
#: This is the full shape, so the swap carries exactly what it carried before — the change
#: is only that unknown fields no longer ride along.
_TABLE_INPUT_FIELDS = frozenset(
    {
        "Name",
        "Description",
        "Owner",
        "LastAccessTime",
        "LastAnalyzedTime",
        "Retention",
        "StorageDescriptor",
        "PartitionKeys",
        "ViewOriginalText",
        "ViewExpandedText",
        "TableType",
        "Parameters",
        "TargetTable",
        "ViewDefinition",
    }
)

#: The subset of ``PartitionInput`` the swap carries. Deliberately narrower than the shape:
#: ``LastAccessTime`` and ``LastAnalyzedTime`` are accepted by Glue but were dropped by the
#: old denylist, and a fix for an outage is the wrong place to start publishing timestamps
#: that nothing has ever read.
_PARTITION_INPUT_FIELDS = frozenset({"Values", "StorageDescriptor", "Parameters"})


def _table_input(table: dict, name: str) -> dict:
    """Turn a GetTable response into a TableInput published under ``name``."""
    payload = {k: v for k, v in table.items() if k in _TABLE_INPUT_FIELDS}
    payload["Name"] = name
    return payload


def _partition_input(partition: dict) -> dict:
    return {k: v for k, v in partition.items() if k in _PARTITION_INPUT_FIELDS}


def _all_partitions(database: str, table: str) -> list[dict]:
    """Every partition of a table, or [] if the table does not exist."""
    partitions: list[dict] = []
    paginator = glue.get_paginator("get_partitions")
    try:
        for page in paginator.paginate(DatabaseName=database, TableName=table):
            partitions.extend(page.get("Partitions", []))
    except glue.exceptions.EntityNotFoundException:
        return []
    return partitions


def _chunks(items: list, size: int):
    for start in range(0, len(items), size):
        yield items[start : start + size]


def _raise_on_batch_errors(operation: str, errors: list) -> None:
    """Glue's batch APIs report per-item failures in the RESPONSE, not as an exception.

    Ignoring them is how a swap reports success while leaving the table pointing half at one
    generation and half at another — the exact inconsistency fault B is about.
    """
    if not errors:
        return
    first = errors[0]
    detail = first.get("ErrorDetail", {})
    raise RuntimeError(
        f"{operation} failed for {len(errors)} partition(s): "
        f"{detail.get('ErrorCode')} {detail.get('ErrorMessage')} "
        f"(values={first.get('PartitionValues')})"
    )


def _move_partitions(database: str, published: str, staged: list[dict]) -> dict:
    """Point the published table's partitions at the freshly built generation.

    Existing values are **updated** rather than deleted and recreated. A delete-then-create
    leaves a window where the table has no partitions at all — a "successful" swap whose
    table reads empty, which is precisely the failure mode the roadmap flags for this PR.
    An update is one call per batch and never passes through an empty state.

    Partitions the new generation does not have are removed last, so the table is never
    missing a value it is about to keep.
    """
    if not staged:
        return {"updated": 0, "created": 0, "deleted": 0}

    existing = {tuple(p["Values"]): p for p in _all_partitions(database, published)}
    staged_by_values = {tuple(p["Values"]): p for p in staged}

    to_update = [p for values, p in staged_by_values.items() if values in existing]
    to_create = [p for values, p in staged_by_values.items() if values not in existing]
    to_delete = [values for values in existing if values not in staged_by_values]

    for batch in _chunks(to_update, _BATCH_UPDATE):
        resp = glue.batch_update_partition(
            DatabaseName=database,
            TableName=published,
            Entries=[
                {"PartitionValueList": p["Values"], "PartitionInput": _partition_input(p)}
                for p in batch
            ],
        )
        _raise_on_batch_errors("batch_update_partition", resp.get("Errors", []))

    for batch in _chunks(to_create, _BATCH_CREATE):
        resp = glue.batch_create_partition(
            DatabaseName=database,
            TableName=published,
            PartitionInputList=[_partition_input(p) for p in batch],
        )
        _raise_on_batch_errors("batch_create_partition", resp.get("Errors", []))

    for batch in _chunks(to_delete, _BATCH_DELETE):
        resp = glue.batch_delete_partition(
            DatabaseName=database,
            TableName=published,
            PartitionsToDelete=[{"Values": list(values)} for values in batch],
        )
        _raise_on_batch_errors("batch_delete_partition", resp.get("Errors", []))

    return {"updated": len(to_update), "created": len(to_create), "deleted": len(to_delete)}


# ==========================================================================================
# The two actions
# ==========================================================================================
def _read_sql(bucket: str, key: str) -> tuple[str, str, str, str, str]:
    """Return ``(sql, database, table, target_bucket, target_prefix)`` from the SQL file."""
    sql = s3.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8")

    loc = _EXTERNAL_LOCATION_RE.search(sql)
    if not loc:
        raise ValueError(f"No external_location found in s3://{bucket}/{key}")

    tbl = _CREATE_TABLE_RE.search(sql)
    if not tbl:
        raise ValueError(f"No 'CREATE TABLE <db>.<table>' found in s3://{bucket}/{key}")

    return sql, tbl.group("db"), tbl.group("table"), loc.group("bucket"), loc.group("prefix")


def prepare(event: dict, correlation_id: str) -> dict:
    """Return the CTAS to run, aimed at a staging table nobody is reading yet."""
    bucket = event["bucket"]
    sql_key = event["sqlKey"]
    run_id = event.get("runId") or correlation_id

    sql, database, table, target_bucket, target_prefix = _read_sql(bucket, sql_key)
    staging_table, staging_prefix = _staging_identity(table, target_prefix, run_id)
    staging_location = f"s3://{target_bucket}/{staging_prefix}"

    # This execution's own prefix, never published. Non-empty only if a previous attempt of
    # THIS execution failed after writing — in which case Athena would refuse to write again.
    deleted = _empty_prefix(target_bucket, staging_prefix)

    # Left over from a previous attempt of this same execution, for the same reason.
    dropped = _drop_table(database, staging_table)

    query_string = _rewrite_for_staging(
        _extract_create_statement(sql), database, staging_table, staging_location
    )

    logger.info(
        "[%s] prepared table=%s.%s staging=%s location=%s stale_objects_deleted=%d "
        "stale_staging_table_dropped=%s",
        correlation_id,
        database,
        table,
        staging_table,
        staging_location,
        deleted,
        dropped,
    )

    return {
        "queryString": query_string,
        "database": database,
        "table": table,
        "stagingTable": staging_table,
        "location": staging_location,
        "publishedLocation": f"s3://{target_bucket}/{target_prefix}",
        "objectsDeleted": deleted,
    }


def promote(event: dict, correlation_id: str) -> dict:
    """Point the published table at the generation the CTAS just built.

    Only reached when the CTAS succeeded, which is the whole point: everything destructive
    happens after there is something to replace the old copy with.
    """
    database = event["database"]
    table = event["table"]
    staging_table = event["stagingTable"]

    staged = glue.get_table(DatabaseName=database, Name=staging_table)["Table"]
    location = staged.get("StorageDescriptor", {}).get("Location")

    created = False
    try:
        glue.update_table(DatabaseName=database, TableInput=_table_input(staged, table))
    except glue.exceptions.EntityNotFoundException:
        # First run, or someone dropped the table by hand. Same end state.
        glue.create_table(DatabaseName=database, TableInput=_table_input(staged, table))
        created = True

    partitions = _move_partitions(database, table, _all_partitions(database, staging_table))

    # The staging CATALOG entry is disposable; its DATA is now the published data, so this
    # deletes a name and nothing else. Last, so a failure above leaves the staging table
    # available to inspect.
    _drop_table(database, staging_table)

    logger.info(
        "[%s] promoted table=%s.%s created=%s location=%s partitions=%s",
        correlation_id,
        database,
        table,
        created,
        location,
        partitions,
    )

    return {
        "database": database,
        "table": table,
        "location": location,
        "created": created,
        "partitions": partitions,
    }


ACTIONS = {"prepare": prepare, "promote": promote}


def handler(event, context):  # noqa: ANN001 - Lambda signature
    correlation_id = event.get("correlation_id") or os.environ.get("CORRELATION_ID", "-")
    action = event.get("action", "prepare")

    if action not in ACTIONS:
        raise ValueError(f"Unknown action {action!r}; expected one of {sorted(ACTIONS)}")

    return ACTIONS[action](event, correlation_id)
