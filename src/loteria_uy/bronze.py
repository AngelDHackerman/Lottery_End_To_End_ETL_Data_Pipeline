"""Local bronze store and the manifest that says what has been fetched.

Two stores, deliberately separate (roadmap-uruguay.md, C3):

- **Bronze** holds raw bytes exactly as served, and only for real draws. Keys mirror the
  future S3 layout (``bronze/country=uy/source=<source>/year=<yyyy>/<source>_<date>.<ext>``),
  so moving to the cloud changes the backend and not the paths. The site regenerates its
  pages from a database with today's template (old extracts cite a 2019 decree), so the
  bytes are "the page as served on ``fetched_at``", never the original document.
- **The manifest** (SQLite) is the cache. A ``no_draw`` day leaves nothing in bronze but
  has a manifest row, and that row is what stops it being requested again.

States in the manifest:

    draw               raw page in bronze
    no_draw            empty, and old enough that "not published yet" is ruled out — final
    not_yet_published  empty but recent — retried on the next run
    missing            the results page lists the game, but this source has nothing — final,
                       and reported, because it is a gap in the source rather than a day off
    error              fetch or classification failed — retried on the next run
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from dataclasses import dataclass
from datetime import date
from pathlib import Path

DRAW = "draw"
NO_DRAW = "no_draw"
NOT_YET_PUBLISHED = "not_yet_published"
MISSING = "missing"
ERROR = "error"

FINAL_STATES = frozenset({DRAW, NO_DRAW, MISSING})

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


class BronzeStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    @staticmethod
    def key(source: str, day: date, extension: str) -> str:
        return (
            f"bronze/country=uy/source={source}/year={day.year}/"
            f"{source}_{day.isoformat()}.{extension}"
        )

    def write(self, key: str, content: bytes) -> None:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(content)
        os.replace(tmp, path)  # never leave a half-written page under the real name

    def read(self, key: str) -> bytes:
        return (self.root / key).read_bytes()


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


class Manifest:
    def __init__(self, path: Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path))
        self._db.row_factory = sqlite3.Row
        self._db.executescript(_SCHEMA)

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

    def record(self, rec: Record) -> None:
        sha = hashlib.sha256(rec.content).hexdigest() if rec.content is not None else None
        size = len(rec.content) if rec.content is not None else None
        day = rec.draw_date.isoformat()
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
                    rec.state,
                    rec.http_status,
                    json.dumps(list(rec.games)),
                    json.dumps(list(rec.warnings)),
                    json.dumps(rec.extra or {}),
                    rec.detail,
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
