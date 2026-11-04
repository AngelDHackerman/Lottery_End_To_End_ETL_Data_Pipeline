"""Copy the local manifest (SQLite) to DynamoDB, once, and prove the copy (UY-042.2; D28).

    python -m sorteos.uy.manifest_migrate --sqlite data/uy/manifest.sqlite \\
        --table lottery-uy-manifest-prod [--check]

``--check`` is read-only: only the verification.

**What is written.** Each ``manifest`` row becomes a STATE item and each ``fetch_log`` row a
LOG item, built by the same functions ``DynamoManifest`` writes with (``state_item`` and
``log_item``), so a migrated key is indistinguishable from one fetched in the cloud. A LOG
item's attempt number is its rank within its key in ``fetch_log`` order.

**Safe to run again.** The table is scanned first and only items that are missing or differ
are written, so a run that stopped halfway finishes the rest. It refuses to write at all when
the table holds a fetch the local manifest does not have, a STATE item newer than the local
row or an item with no local row: by then the cloud has taken over (UY-043), and copying the
local file over it would undo fetches.

**The proof**, after writing or with ``--check``:

- every item of the table equals the one SQLite gives, field by field, and nothing else is
  there: 21,726 STATE and 21,803 LOG items on 2026-11-02;
- through the ``Manifest`` interface, both backends answer the same ``summary()``,
  ``date_range()`` of every source and ``open_keys()`` (with ``manual_overrides.csv``).

The exit code is 0 when the proof holds, 1 when it does not and 2 when the write was refused.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

from boto3.dynamodb.types import TypeDeserializer

from sorteos.core import manifest as mf
from sorteos.core import manifest_dynamodb as md
from sorteos.uy import backfill

Key = tuple[str, str]  # (pk, sk)

BATCH = 25  # BatchWriteItem's limit
MAX_ROUNDS = 8  # retries of UnprocessedItems, with backoff
SHOW = 10

_deserializer = TypeDeserializer()


# --- both sides as plain items ------------------------------------------------------------


def expected_items(sqlite_path: Path) -> dict[Key, dict[str, Any]]:
    """Every item the table must hold, built from SQLite without changing it."""
    db = sqlite3.connect(f"file:{sqlite_path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        states = [dict(r) for r in db.execute("SELECT * FROM manifest")]
        logs = [dict(r) for r in db.execute("SELECT * FROM fetch_log ORDER BY id")]
    finally:
        db.close()
    out: dict[Key, dict[str, Any]] = {}
    for row in states:
        item = md.state_item(row)
        out[(item["pk"], item["sk"])] = item
    rank: dict[str, int] = defaultdict(int)
    for row in logs:
        pk = md.partition_key(row["source"], row["draw_date"])
        rank[pk] += 1
        item = md.log_item(row, rank[pk])
        out[(item["pk"], item["sk"])] = item
    return out


def _plain(raw: dict[str, Any]) -> dict[str, Any]:
    item = {k: _deserializer.deserialize(v) for k, v in raw.items()}
    return {k: int(v) if isinstance(v, Decimal) else v for k, v in item.items()}


def table_items(client, table: str) -> dict[Key, dict[str, Any]]:
    out: dict[Key, dict[str, Any]] = {}
    for page in client.get_paginator("scan").paginate(TableName=table, ConsistentRead=True):
        for raw in page["Items"]:
            item = _plain(raw)
            out[(item["pk"], item["sk"])] = item
    return out


# --- writing ------------------------------------------------------------------------------


def conflicts(expected: dict[Key, dict], current: dict[Key, dict]) -> list[str]:
    """Items that say the cloud already moved past the local manifest."""
    found = []
    for key, item in current.items():
        mine = expected.get(key)
        if mine is None:
            found.append(f"{key[0]} {key[1]}: in the table, not in SQLite")
        elif key[1] == md.STATE_SK and item.get("fetched_at", "") > mine["fetched_at"]:
            found.append(f"{key[0]}: fetched {item['fetched_at']} in the table, newer than SQLite")
    return sorted(found)


def write(client, table: str, items: list[dict[str, Any]], sleep=time.sleep) -> None:
    for start in range(0, len(items), BATCH):
        pending = [{"PutRequest": {"Item": md.to_dynamo(i)}} for i in items[start : start + BATCH]]
        for attempt in range(MAX_ROUNDS):
            left = client.batch_write_item(RequestItems={table: pending}).get(
                "UnprocessedItems", {}
            )
            pending = left.get(table, [])
            if not pending:
                break
            sleep(min(0.1 * 2**attempt, 5))
        else:
            raise RuntimeError(f"DynamoDB kept {len(pending)} items unprocessed; run again")


# --- the proof ----------------------------------------------------------------------------


def item_problems(expected: dict[Key, dict], current: dict[Key, dict]) -> list[str]:
    problems = [f"missing: {k[0]} {k[1]}" for k in expected if k not in current]
    problems += [
        f"different: {k[0]} {k[1]}" for k in expected if k in current and current[k] != expected[k]
    ]
    problems += [f"extra: {k[0]} {k[1]}" for k in current if k not in expected]
    return sorted(problems)


def interface_problems(local: mf.Manifest, cloud: mf.Manifest) -> list[str]:
    problems = []
    summary = local.summary()
    if cloud.summary() != summary:
        problems.append("summary() differs")
    for source in sorted({row[0] for row in summary}):
        if cloud.date_range(source) != local.date_range(source):
            problems.append(f"date_range({source}) differs")
    if cloud.open_keys() != local.open_keys():
        problems.append("open_keys() differs")
    return problems


def counts(items: dict[Key, dict]) -> tuple[int, int]:
    states = sum(1 for _, sk in items if sk == md.STATE_SK)
    return states, len(items) - states


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m sorteos.uy.manifest_migrate",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--sqlite", type=Path, required=True, help="the local manifest.sqlite")
    p.add_argument("--table", required=True, help="the DynamoDB manifest table")
    p.add_argument("--check", action="store_true", help="only verify; write nothing")
    return p


def main(argv: list[str] | None = None, client=None, overrides=None) -> int:
    args = build_parser().parse_args(argv)
    if not args.sqlite.is_file():
        print(f"{args.sqlite} does not exist", file=sys.stderr)
        return 2
    if client is None:  # pragma: no cover - the tests pass a moto client
        import boto3

        client = boto3.client("dynamodb")
    if overrides is None:  # pragma: no cover - the tests pass their own
        overrides = backfill.load_overrides()

    expected = expected_items(args.sqlite)
    current = table_items(client, args.table)
    print(f"SQLite:  {counts(expected)[0]:>7,} STATE  {counts(expected)[1]:>7,} LOG")
    print(f"table:   {counts(current)[0]:>7,} STATE  {counts(current)[1]:>7,} LOG  (before)")

    if not args.check:
        refused = conflicts(expected, current)
        if refused:
            print(f"\nREFUSED: the table is ahead of SQLite in {len(refused):,} items:")
            print("\n".join(f"  {line}" for line in refused[:SHOW]))
            return 2
        todo = [item for key, item in expected.items() if current.get(key) != item]
        print(f"writing: {len(todo):>7,} items")
        write(client, args.table, todo)
        current = table_items(client, args.table)
        print(f"table:   {counts(current)[0]:>7,} STATE  {counts(current)[1]:>7,} LOG  (after)")

    problems = item_problems(expected, current)
    local = mf.SqliteManifest(args.sqlite, overrides)
    try:
        problems += interface_problems(local, md.DynamoManifest(args.table, overrides, client))
    finally:
        local.close()
    if problems:
        print(f"\nFAIL: {len(problems):,} problems")
        print("\n".join(f"  {line}" for line in problems[:SHOW]))
        return 1
    print("\nOK: the table is the local manifest, item by item, and answers the same.")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
