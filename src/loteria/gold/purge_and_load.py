"""Gold CTAS pre-flight: make a gold table's location safe to (re)create, then hand
the CREATE statement back to Step Functions.

PR-022 wires the Gold layer into the ETL Step Function. Each iteration of the
``BuildGold`` Map state invokes this Lambda once, with an event like::

    {"bucket": "lottery-partitioned-storage-prod", "sqlKey": "sql/gold/01_gold_draw_summary.sql"}

Two facts force this helper to exist between "start the crawlers" and "run the CTAS":

1. **Athena runs ONE statement per StartQueryExecution.** The files in ``sql/gold/``
   each hold ``DROP TABLE ...; CREATE TABLE ... AS SELECT ...``. Passing both to Athena
   fails, so this Lambda performs the DROP itself (``glue:DeleteTable``, idempotent) and
   returns only the ``CREATE TABLE`` statement for the Athena task to run.

2. **Athena CTAS refuses a non-empty ``external_location``** (``HIVE_PATH_ALREADY_EXISTS``).
   The manual PR-021 runs already left Parquet under ``gold/<name>/``, so this Lambda
   empties that prefix before the CTAS. The bucket has versioning on (PR-002/005), so the
   deletes drop delete-markers — data history is retained, the location just reads empty.

The table name, target location, and the CREATE statement are all parsed from the SQL
file itself, so the file stays the single source of truth (no duplicated config in TF).
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

    Mirrors ``DROP TABLE IF EXISTS`` — a missing table is not an error.
    """
    try:
        glue.delete_table(DatabaseName=database, Name=table)
        return True
    except glue.exceptions.EntityNotFoundException:
        return False


def handler(event, context):  # noqa: ANN001 - Lambda signature
    correlation_id = event.get("correlation_id") or os.environ.get("CORRELATION_ID", "-")
    bucket = event["bucket"]
    sql_key = event["sqlKey"]

    logger.info("[%s] purge+load start bucket=%s key=%s", correlation_id, bucket, sql_key)

    sql = s3.get_object(Bucket=bucket, Key=sql_key)["Body"].read().decode("utf-8")

    loc = _EXTERNAL_LOCATION_RE.search(sql)
    if not loc:
        raise ValueError(f"No external_location found in s3://{bucket}/{sql_key}")
    target_bucket = loc.group("bucket")
    target_prefix = loc.group("prefix")

    tbl = _CREATE_TABLE_RE.search(sql)
    if not tbl:
        raise ValueError(f"No 'CREATE TABLE <db>.<table>' found in s3://{bucket}/{sql_key}")
    database = tbl.group("db")
    table = tbl.group("table")

    dropped = _drop_table(database, table)
    deleted = _empty_prefix(target_bucket, target_prefix)
    query_string = _extract_create_statement(sql)

    logger.info(
        "[%s] ready table=%s.%s dropped=%s objects_deleted=%d location=s3://%s/%s",
        correlation_id,
        database,
        table,
        dropped,
        deleted,
        target_bucket,
        target_prefix,
    )

    # Consumed by the Athena StartQueryExecution.sync task via ResultSelector.
    return {
        "queryString": query_string,
        "database": database,
        "table": table,
        "location": f"s3://{target_bucket}/{target_prefix}",
        "objectsDeleted": deleted,
    }
