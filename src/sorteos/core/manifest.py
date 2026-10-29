"""The manifest: what has been fetched, what it turned out to be, and what is still open.

It is the cache of the ingestion (roadmap-uruguay.md, C3). A ``no_draw`` day leaves nothing
in bronze but has a manifest row, and that row is what stops it being requested again.

States:

    draw               raw page in bronze
    no_draw            empty, and old enough that "not published yet" is ruled out — final
    not_yet_published  empty but recent — retried on the next run
    missing            the results page lists the game, but this source has nothing — final,
                       and reported, because it is a gap in the source rather than a day off
    error              fetch or classification failed — retried on the next run

``Manifest`` is the interface the ingestion uses (docs/uruguay/DESIGN.md, D12): SQLite is the
local backend, and the cloud one is decided in UY-040. Two rules sit on top of the stored
rows, and both are part of the contract, not of SQLite:

- **Three identical failures become ``missing``** (D11, P8). When a fetch fails, the last
  rows of ``fetch_log`` for that key are compared by their signature: (``http_status``,
  ``content_sha256``), or the error ``detail`` when nothing answered. A 403 that always
  returns the same 146 bytes is a file that is not there; a 403 with another body, or a
  timeout, may be a bad moment of the site, so counting attempts alone is not enough.
  ``fetch_log`` keeps the ``error`` it saw; only the manifest row records the decision.
- **The effective state** of a key is its manual override when it has one, else the
  manifest's (D10, P9). Overrides live in a reviewed CSV, never in the manifest, so a
  ``--refresh`` cannot erase them and what the classifier saw is never edited by hand.
"""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Protocol

DRAW = "draw"
NO_DRAW = "no_draw"
NOT_YET_PUBLISHED = "not_yet_published"
MISSING = "missing"
ERROR = "error"

FINAL_STATES = frozenset({DRAW, NO_DRAW, MISSING})

# How many identical failures in a row close a key (DESIGN.md, D11).
REPEATED_FAILURES = 3

# A person may say a day had nothing; nobody may say it had a draw that bronze does not hold.
OVERRIDE_STATES = frozenset({NO_DRAW, MISSING})

_SCHEMA = """
CREATE TABLE IF NOT EXISTS manifest (
    source             TEXT NOT NULL,
    draw_date          TEXT NOT NULL,
    url                TEXT NOT NULL,
    state              TEXT NOT NULL,
    http_status        INTEGER,
    games              TEXT,
    warnings           TEXT,
    extra              TEXT,
    detail             TEXT,
    content_sha256     TEXT,
    bytes              INTEGER,
    bronze_key         TEXT,
    content_type       TEXT,
    last_modified      TEXT,
    classifier_version TEXT,
    attempts           INTEGER NOT NULL DEFAULT 0,
    first_fetched_at   TEXT NOT NULL,
    fetched_at         TEXT NOT NULL,
    PRIMARY KEY (source, draw_date)
);
CREATE TABLE IF NOT EXISTS fetch_log (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    source         TEXT NOT NULL,
    draw_date      TEXT NOT NULL,
    url            TEXT NOT NULL,
    state          TEXT NOT NULL,
    http_status    INTEGER,
    content_sha256 TEXT,
    detail         TEXT,
    fetched_at     TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class Record:
    source: str
    draw_date: date
    url: str
    state: str
    fetched_at: str
    http_status: int | None = None
    games: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    extra: dict | None = None
    detail: str = ""
    content: bytes | None = None
    bronze_key: str | None = None
    content_type: str | None = None
    last_modified: str | None = None
    classifier_version: str | None = None


@dataclass(frozen=True)
class Override:
    """One row of ``manual_overrides.csv``: a person's decision about one key, with its source."""

    source: str
    draw_date: date
    state: str
    calendar_event_date: date
    reason: str
    decided_by: str
    decided_on: date


class Manifest(Protocol):
    overrides: Mapping[tuple[str, date], Override]

    def get(self, source: str, day: date) -> dict | None: ...

    def record(self, rec: Record) -> str:
        """Store one fetch and return the state the key ends up in."""
        ...

    def effective_state(self, source: str, day: date) -> str | None: ...

    def history(self, source: str, day: date, limit: int) -> list[dict]:
        """The last ``limit`` rows of ``fetch_log`` for the key, oldest first."""
        ...

    def summary(self) -> list[tuple[str, str, int]]: ...

    def date_range(self, source: str) -> tuple[str, str] | None: ...

    def open_keys(self) -> list[tuple[str, date]]:
        """Every key whose effective state is not final, oldest first."""
        ...

    def close(self) -> None: ...


def failure_signature(http_status: int | None, content_sha256: str | None, detail: str) -> tuple:
    if http_status is None:
        return ("no response", detail)
    return (http_status, content_sha256)


def repeats_failure(previous: list[dict], current: Record, sha: str | None) -> bool:
    """True when ``current`` is the REPEATED_FAILURES-th identical error in a row."""
    if current.state != ERROR or len(previous) < REPEATED_FAILURES - 1:
        return False
    signature = failure_signature(current.http_status, sha, current.detail)
    return all(
        row["state"] == ERROR
        and failure_signature(row["http_status"], row["content_sha256"], row["detail"] or "")
        == signature
        for row in previous[-(REPEATED_FAILURES - 1) :]
    )


def effective_state(
    overrides: Mapping[tuple[str, date], Override], source: str, day: date, stored: str | None
) -> str | None:
    override = overrides.get((source, day))
    return override.state if override else stored


class SqliteManifest:
    def __init__(
        self, path: Path, overrides: Mapping[tuple[str, date], Override] | None = None
    ) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path))
        self._db.row_factory = sqlite3.Row
        self._db.executescript(_SCHEMA)
        self.overrides = dict(overrides or {})

    def close(self) -> None:
        self._db.close()

    def get(self, source: str, day: date) -> dict | None:
        row = self._db.execute(
            "SELECT * FROM manifest WHERE source = ? AND draw_date = ?", (source, day.isoformat())
        ).fetchone()
        if row is None:
            return None
        out = dict(row)
        out["games"] = tuple(json.loads(out["games"] or "[]"))
        out["warnings"] = tuple(json.loads(out["warnings"] or "[]"))
        out["extra"] = json.loads(out["extra"] or "{}")
        return out

    def effective_state(self, source: str, day: date) -> str | None:
        row = self.get(source, day)
        return effective_state(self.overrides, source, day, row["state"] if row else None)

    def history(self, source: str, day: date, limit: int) -> list[dict]:
        rows = self._db.execute(
            "SELECT * FROM fetch_log WHERE source = ? AND draw_date = ? ORDER BY id DESC LIMIT ?",
            (source, day.isoformat(), limit),
        ).fetchall()
        return [dict(r) for r in reversed(rows)]

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
        with self._db:
            self._db.execute(
                """
                INSERT INTO manifest (source, draw_date, url, state, http_status, games,
                    warnings, extra, detail, content_sha256, bytes, bronze_key, content_type,
                    last_modified, classifier_version, attempts, first_fetched_at, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                ON CONFLICT (source, draw_date) DO UPDATE SET
                    url = excluded.url, state = excluded.state,
                    http_status = excluded.http_status, games = excluded.games,
                    warnings = excluded.warnings, extra = excluded.extra,
                    detail = excluded.detail, content_sha256 = excluded.content_sha256,
                    bytes = excluded.bytes, bronze_key = excluded.bronze_key,
                    content_type = excluded.content_type,
                    last_modified = excluded.last_modified,
                    classifier_version = excluded.classifier_version,
                    attempts = manifest.attempts + 1, fetched_at = excluded.fetched_at
                """,
                (
                    rec.source,
                    day,
                    rec.url,
                    state,
                    rec.http_status,
                    json.dumps(list(rec.games)),
                    json.dumps(list(rec.warnings)),
                    json.dumps(rec.extra or {}),
                    detail,
                    sha,
                    size,
                    rec.bronze_key,
                    rec.content_type,
                    rec.last_modified,
                    rec.classifier_version,
                    rec.fetched_at,
                    rec.fetched_at,
                ),
            )
            # The log keeps what the fetch saw, so the signatures stay comparable.
            self._db.execute(
                """
                INSERT INTO fetch_log (source, draw_date, url, state, http_status,
                    content_sha256, detail, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rec.source,
                    day,
                    rec.url,
                    rec.state,
                    rec.http_status,
                    sha,
                    rec.detail,
                    rec.fetched_at,
                ),
            )
        return state

    def summary(self) -> list[tuple[str, str, int]]:
        return [
            tuple(r)
            for r in self._db.execute(
                "SELECT source, state, COUNT(*) FROM manifest GROUP BY source, state "
                "ORDER BY source, state"
            )
        ]

    def date_range(self, source: str) -> tuple[str, str] | None:
        row = self._db.execute(
            "SELECT MIN(draw_date), MAX(draw_date) FROM manifest WHERE source = ? AND state = ?",
            (source, DRAW),
        ).fetchone()
        return (row[0], row[1]) if row and row[0] else None

    def open_keys(self) -> list[tuple[str, date]]:
        final = sorted(FINAL_STATES)
        rows = self._db.execute(
            f"SELECT source, draw_date, state FROM manifest "
            f"WHERE state NOT IN ({', '.join('?' * len(final))}) ORDER BY draw_date, source",
            final,
        )
        keys = [(source, date.fromisoformat(day), state) for source, day, state in rows]
        # An override closes a key the classifier left open (the 2019 strike days).
        return [
            (source, day)
            for source, day, state in keys
            if effective_state(self.overrides, source, day, state) not in FINAL_STATES
        ]


class OverrideError(ValueError):
    pass


_OVERRIDE_COLUMNS = (
    "source",
    "draw_date",
    "state",
    "calendar_event_date",
    "reason",
    "decided_by",
    "decided_on",
)


def _iso_date(value: str, where: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise OverrideError(f"{where}: {value!r} is not a YYYY-MM-DD date") from None


def load_overrides(
    path: Path, *, calendar_events: Path, sources: Collection[str]
) -> dict[tuple[str, date], Override]:
    """Load ``manual_overrides.csv`` strictly. Every row is one source and one date: no
    wildcards, so a new ``error`` still needs a person to look at it."""
    with open(calendar_events, encoding="utf-8", newline="") as fh:
        events = {row["event_date"] for row in csv.DictReader(fh)}
    out: dict[tuple[str, date], Override] = {}
    with open(path, encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        if tuple(reader.fieldnames or ()) != _OVERRIDE_COLUMNS:
            raise OverrideError(f"{path.name}: columns must be {', '.join(_OVERRIDE_COLUMNS)}")
        for line, row in enumerate(reader, start=2):
            where = f"{path.name}:{line}"
            if None in row or any(not (row[c] or "").strip() for c in _OVERRIDE_COLUMNS):
                raise OverrideError(f"{where}: every column needs a value, and no more columns")
            if row["source"] not in sources:
                raise OverrideError(f"{where}: unknown source {row['source']!r}")
            if row["state"] not in OVERRIDE_STATES:
                raise OverrideError(
                    f"{where}: state must be one of {sorted(OVERRIDE_STATES)}, "
                    f"not {row['state']!r}"
                )
            if row["calendar_event_date"] not in events:
                raise OverrideError(
                    f"{where}: calendar_event_date {row['calendar_event_date']!r} "
                    f"is not in {calendar_events.name}"
                )
            override = Override(
                source=row["source"],
                draw_date=_iso_date(row["draw_date"], where),
                state=row["state"],
                calendar_event_date=_iso_date(row["calendar_event_date"], where),
                reason=row["reason"],
                decided_by=row["decided_by"],
                decided_on=_iso_date(row["decided_on"], where),
            )
            key = (override.source, override.draw_date)
            if key in out:
                raise OverrideError(f"{where}: {key[0]} {key[1]} is already overridden")
            out[key] = override
    return out
