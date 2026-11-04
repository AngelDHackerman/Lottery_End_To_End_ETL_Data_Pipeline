"""The manifest on DynamoDB (UY-042.2): the cloud backend of ``Manifest`` (DESIGN.md D12, D28).

Same contract as ``SqliteManifest``, and the same tests run against both. The table is
``terraform/uy/manifest.tf`` (P16), one item per row of either SQLite table:

    pk                     sk                         SQLite
    <source>#<YYYY-MM-DD>  STATE                      a row of manifest
    <source>#<YYYY-MM-DD>  LOG#<fetched_at>#<n:06d>   a row of fetch_log

- Every column keeps its SQLite name, and ``games``, ``warnings`` and ``extra`` keep their JSON
  text, so a migrated item is the SQLite row with two keys added. A NULL is a missing attribute.
- ``n`` is the key's attempt number, so two fetches of a key in the same second still sort in
  order. ``history()`` is a Query on ``pk`` with ``sk`` beginning ``LOG#``.
- ``open`` = ``"1"`` is on a STATE item only while its state is not final: that is what puts it
  in the sparse index ``open-keys`` that ``open_keys()`` queries. Overrides apply in the code.
- ``record()`` reads the STATE item and writes it with the LOG item in one transaction that
  holds only if ``attempts`` is still what it read. Two runs fetching the same key at once fail
  the second one loudly instead of losing a row (D28), and the LOG item never overwrites one.

Reads of one key are strongly consistent: ``record()`` decides on the history it just wrote.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping
from datetime import date
from typing import Any

from boto3.dynamodb.types import TypeDeserializer, TypeSerializer

from sorteos.core.manifest import (
    DRAW,
    FINAL_STATES,
    MISSING,
    REPEATED_FAILURES,
    Override,
    Record,
    effective_state,
    repeats_failure,
)

STATE_SK = "STATE"
LOG_PREFIX = "LOG#"
OPEN_INDEX = "open-keys"
OPEN = "1"

# The columns of each SQLite table, in its order: get() and history() return these keys.
MANIFEST_COLUMNS = (
    "source",
    "draw_date",
    "url",
    "state",
    "http_status",
    "games",
    "warnings",
    "extra",
    "detail",
    "content_sha256",
    "bytes",
    "bronze_key",
    "content_type",
    "last_modified",
    "classifier_version",
    "attempts",
    "first_fetched_at",
    "fetched_at",
)
LOG_COLUMNS = (
    "source",
    "draw_date",
    "url",
    "state",
    "http_status",
    "content_sha256",
    "detail",
    "fetched_at",
)
INT_COLUMNS = frozenset({"http_status", "bytes", "attempts"})

_serializer = TypeSerializer()
_deserializer = TypeDeserializer()


class ConcurrentWriteError(RuntimeError):
    """Another run wrote this key between our read and our write."""


def partition_key(source: str, day: str) -> str:
    return f"{source}#{day}"


def log_sort_key(fetched_at: str, n: int) -> str:
    return f"{LOG_PREFIX}{fetched_at}#{n:06d}"


def state_item(row: Mapping[str, Any]) -> dict[str, Any]:
    """A manifest row (SQLite's columns, JSON as text) as a STATE item."""
    item = {k: row[k] for k in MANIFEST_COLUMNS if row.get(k) is not None}
    item["pk"] = partition_key(row["source"], row["draw_date"])
    item["sk"] = STATE_SK
    if row["state"] not in FINAL_STATES:
        item["open"] = OPEN
    return item


def log_item(row: Mapping[str, Any], n: int) -> dict[str, Any]:
    """A fetch_log row as a LOG item; ``n`` is its attempt number within the key."""
    item = {k: row[k] for k in LOG_COLUMNS if row.get(k) is not None}
    item["pk"] = partition_key(row["source"], row["draw_date"])
    item["sk"] = log_sort_key(row["fetched_at"], n)
    return item


def to_dynamo(item: Mapping[str, Any]) -> dict[str, Any]:
    return {k: _serializer.serialize(v) for k, v in item.items()}


def from_dynamo(raw: Mapping[str, Any], columns: tuple[str, ...]) -> dict[str, Any]:
    """Back to a SQLite-shaped row: every column present, NULL as None, numbers as int."""
    plain = {k: _deserializer.deserialize(v) for k, v in raw.items()}
    return {
        k: (int(plain[k]) if k in INT_COLUMNS and plain.get(k) is not None else plain.get(k))
        for k in columns
    }


def decoded(row: dict) -> dict:
    """A STATE row as ``get()`` returns it: ``games``/``warnings`` as tuples, ``extra`` a dict."""
    row = dict(row)
    row["games"] = tuple(json.loads(row["games"] or "[]"))
    row["warnings"] = tuple(json.loads(row["warnings"] or "[]"))
    row["extra"] = json.loads(row["extra"] or "{}")
    return row


class DynamoManifest:
    def __init__(
        self,
        table: str,
        overrides: Mapping[tuple[str, date], Override] | None = None,
        client=None,
    ) -> None:
        if client is None:  # pragma: no cover - the tests pass a moto client
            import boto3

            client = boto3.client("dynamodb")
        self._client = client
        self._table = table
        self.overrides = dict(overrides or {})

    def close(self) -> None:
        pass

    # --- one key ---------------------------------------------------------------------------

    def _state(self, source: str, day: str) -> dict | None:
        raw = self._client.get_item(
            TableName=self._table,
            Key=to_dynamo({"pk": partition_key(source, day), "sk": STATE_SK}),
            ConsistentRead=True,
        ).get("Item")
        return from_dynamo(raw, MANIFEST_COLUMNS) if raw else None

    def get(self, source: str, day: date) -> dict | None:
        row = self._state(source, day.isoformat())
        return decoded(row) if row else None

    def effective_state(self, source: str, day: date) -> str | None:
        row = self._state(source, day.isoformat())
        return effective_state(self.overrides, source, day, row["state"] if row else None)

    def history(self, source: str, day: date, limit: int) -> list[dict]:
        if limit <= 0:
            return []
        raw = self._client.query(
            TableName=self._table,
            KeyConditionExpression="pk = :pk AND begins_with(sk, :log)",
            ExpressionAttributeValues=to_dynamo(
                {":pk": partition_key(source, day.isoformat()), ":log": LOG_PREFIX}
            ),
            ScanIndexForward=False,
            Limit=limit,
            ConsistentRead=True,
        )["Items"]
        return [from_dynamo(item, LOG_COLUMNS) for item in reversed(raw)]

    def record(self, rec: Record) -> str:
        sha = hashlib.sha256(rec.content).hexdigest() if rec.content is not None else None
        size = len(rec.content) if rec.content is not None else None
        day = rec.draw_date.isoformat()
        state, detail = rec.state, rec.detail
        if repeats_failure(
            self.history(rec.source, rec.draw_date, REPEATED_FAILURES - 1), rec, sha
        ):
            state = MISSING
            detail = f"same failure {REPEATED_FAILURES} times in a row: {rec.detail}"

        previous = self._state(rec.source, day)
        attempts = (previous["attempts"] if previous else 0) + 1
        row = {
            "source": rec.source,
            "draw_date": day,
            "url": rec.url,
            "state": state,
            "http_status": rec.http_status,
            "games": json.dumps(list(rec.games)),
            "warnings": json.dumps(list(rec.warnings)),
            "extra": json.dumps(rec.extra or {}),
            "detail": detail,
            "content_sha256": sha,
            "bytes": size,
            "bronze_key": rec.bronze_key,
            "content_type": rec.content_type,
            "last_modified": rec.last_modified,
            "classifier_version": rec.classifier_version,
            "attempts": attempts,
            "first_fetched_at": previous["first_fetched_at"] if previous else rec.fetched_at,
            "fetched_at": rec.fetched_at,
        }
        # The log keeps what the fetch saw, so the signatures stay comparable.
        log = {
            "source": rec.source,
            "draw_date": day,
            "url": rec.url,
            "state": rec.state,
            "http_status": rec.http_status,
            "content_sha256": sha,
            "detail": rec.detail,
            "fetched_at": rec.fetched_at,
        }
        if previous:
            guard = {
                "ConditionExpression": "attempts = :seen",
                "ExpressionAttributeValues": to_dynamo({":seen": attempts - 1}),
            }
        else:
            guard = {"ConditionExpression": "attribute_not_exists(pk)"}
        try:
            self._client.transact_write_items(
                TransactItems=[
                    {
                        "Put": {
                            "TableName": self._table,
                            "Item": to_dynamo(state_item(row)),
                            **guard,
                        }
                    },
                    {
                        "Put": {
                            "TableName": self._table,
                            "Item": to_dynamo(log_item(log, attempts)),
                            "ConditionExpression": "attribute_not_exists(sk)",
                        }
                    },
                ]
            )
        except self._client.exceptions.TransactionCanceledException as exc:
            raise ConcurrentWriteError(
                f"{rec.source} {day}: another run wrote this key at the same time; "
                "nothing was written, run again"
            ) from exc
        return state

    # --- the whole table -------------------------------------------------------------------

    def snapshot(self) -> ManifestSnapshot:
        """Every STATE row, read once with one Scan, as a read-only manifest (UY-042.4.1).

        For a reader that asks about thousands of keys and writes none (the silver Lambda):
        one Scan of the table instead of two GetItems per day. LOG items are not read.
        """
        pages = self._client.get_paginator("scan").paginate(
            TableName=self._table,
            FilterExpression="sk = :state",
            ExpressionAttributeValues=to_dynamo({":state": STATE_SK}),
            ConsistentRead=True,
        )
        rows = [from_dynamo(raw, MANIFEST_COLUMNS) for page in pages for raw in page["Items"]]
        return ManifestSnapshot(rows, self.overrides)

    def _states(self) -> Iterator[dict]:
        pages = self._client.get_paginator("scan").paginate(
            TableName=self._table,
            FilterExpression="sk = :state",
            ExpressionAttributeValues=to_dynamo({":state": STATE_SK}),
            ProjectionExpression="#s, draw_date, #st",
            ExpressionAttributeNames={"#s": "source", "#st": "state"},
        )
        for page in pages:
            for raw in page["Items"]:
                yield {k: _deserializer.deserialize(v) for k, v in raw.items()}

    def summary(self) -> list[tuple[str, str, int]]:
        counts: dict[tuple[str, str], int] = {}
        for row in self._states():
            key = (row["source"], row["state"])
            counts[key] = counts.get(key, 0) + 1
        return [(source, state, n) for (source, state), n in sorted(counts.items())]

    def date_range(self, source: str) -> tuple[str, str] | None:
        days = [
            r["draw_date"] for r in self._states() if r["source"] == source and r["state"] == DRAW
        ]
        return (min(days), max(days)) if days else None

    def open_keys(self) -> list[tuple[str, date]]:
        pages = self._client.get_paginator("query").paginate(
            TableName=self._table,
            IndexName=OPEN_INDEX,
            KeyConditionExpression="#o = :open",
            ExpressionAttributeNames={"#o": "open"},
            ExpressionAttributeValues=to_dynamo({":open": OPEN}),
        )
        keys = []
        for page in pages:
            for raw in page["Items"]:
                row = {k: _deserializer.deserialize(v) for k, v in raw.items()}
                source, day = row["pk"].rsplit("#", 1)
                keys.append((day, source, row["state"]))
        keys.sort()
        # The index only holds stored states that are not final; an override can still close
        # one (the 2019 strike days), exactly as in SqliteManifest.
        return [
            (source, date.fromisoformat(day))
            for day, source, state in keys
            if state not in FINAL_STATES
            and effective_state(self.overrides, source, date.fromisoformat(day), state)
            not in FINAL_STATES
        ]


class ReadOnlyManifestError(RuntimeError):
    pass


class ManifestSnapshot:
    """The manifest's STATE rows at one moment, answered from memory (UY-042.4.1).

    The same answers as the manifest it was taken from, for the methods a reader uses. It
    never writes: ``record()`` raises, and so does ``history()``, whose LOG rows it never read.
    """

    def __init__(
        self,
        rows: list[dict],
        overrides: Mapping[tuple[str, date], Override] | None = None,
    ) -> None:
        self.overrides = dict(overrides or {})
        self._rows = {(r["source"], r["draw_date"]): r for r in rows}

    def __len__(self) -> int:
        return len(self._rows)

    def rows(self) -> list[dict]:
        """Every stored row, undecoded (JSON columns as text), sorted by key."""
        return [self._rows[k] for k in sorted(self._rows)]

    def close(self) -> None:
        pass

    def get(self, source: str, day: date) -> dict | None:
        row = self._rows.get((source, day.isoformat()))
        return decoded(row) if row else None

    def effective_state(self, source: str, day: date) -> str | None:
        row = self._rows.get((source, day.isoformat()))
        return effective_state(self.overrides, source, day, row["state"] if row else None)

    def summary(self) -> list[tuple[str, str, int]]:
        counts: dict[tuple[str, str], int] = {}
        for (source, _), row in self._rows.items():
            key = (source, row["state"])
            counts[key] = counts.get(key, 0) + 1
        return [(source, state, n) for (source, state), n in sorted(counts.items())]

    def date_range(self, source: str) -> tuple[str, str] | None:
        days = [d for (s, d), r in self._rows.items() if s == source and r["state"] == DRAW]
        return (min(days), max(days)) if days else None

    def open_keys(self) -> list[tuple[str, date]]:
        keys = sorted((d, s) for (s, d), r in self._rows.items() if r["state"] not in FINAL_STATES)
        return [
            (s, date.fromisoformat(d))
            for d, s in keys
            if effective_state(
                self.overrides, s, date.fromisoformat(d), self._rows[(s, d)]["state"]
            )
            not in FINAL_STATES
        ]

    def history(self, source: str, day: date, limit: int) -> list[dict]:
        raise ReadOnlyManifestError("a snapshot holds no fetch_log; use DynamoManifest")

    def record(self, rec: Record) -> str:
        raise ReadOnlyManifestError("a snapshot is read-only; record() goes to DynamoManifest")
