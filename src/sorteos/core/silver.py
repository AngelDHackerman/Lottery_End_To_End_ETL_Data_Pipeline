"""Silver: explicit pyarrow schemas, the checks before a write, and the per-year rewrite.

Every table is declared here with its types (DESIGN.md, «Convenciones»), because the two traps
of Parquet typing are silent: a column that comes all ``None`` is written as the ``Null`` type,
and a Python int as ``int64`` under a catalog that says ``int``. Both make the table unreadable
once Athena declares it. A schema written by hand avoids both.

A write replaces a whole partition (D17): the rows of one table, country and year, every game
at once. A game with no rows left that year loses its partition. Running it again gives the
same files, with no upsert logic, which Parquet does not have.

Before writing, the rows are checked, because pyarrow checks less than it seems: it drops a
key that is not in the schema without a word and does not enforce ``nullable=False``. So a
row must have exactly the table's columns, its key columns filled, a key no other row has, and
only ``dq_flags`` of the catalog for that table (D22). The catalog is a parameter: its flags
belong to a country (``sorteos/uy/dq_flags.py``), and this module knows none.

The partition columns (``country``, ``game``, ``year``) go in the path and not in the file,
as in ``master``'s Silver: Athena shows them as columns all the same, and pandas or pyarrow
read the folder without a column that would be in both places.
"""

from __future__ import annotations

import csv
import hashlib
import os
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import pyarrow as pa
import pyarrow.dataset as pads
import pyarrow.parquet as pq

FILE_NAME = "part-0.parquet"

# The lineage of PR-045 plus two columns (DESIGN.md, «Convenciones»). ``ingested_at`` is UTC
# and timezone-naive, like master's: Athena's ``timestamp`` has no zone.
LINEAGE = (
    pa.field("ingested_at", pa.timestamp("us"), nullable=False),
    pa.field("run_id", pa.string()),
    pa.field("source_key", pa.string()),
    pa.field("source_sha256", pa.string()),
    pa.field("parser_version", pa.string()),
)
_DRAW = (
    pa.field("country", pa.string(), nullable=False),
    pa.field("operator", pa.string(), nullable=False),
    pa.field("game", pa.string(), nullable=False),
    pa.field("draw_date", pa.date32(), nullable=False),
)
_FLAGS = pa.field("dq_flags", pa.list_(pa.string()), nullable=False)
_LOCAL_TIME = pa.timestamp("us")  # Montevideo wall-clock time, as published (P2)


class SilverError(ValueError):
    pass


@dataclass(frozen=True)
class Table:
    name: str
    schema: pa.Schema  # every column, the partition ones included
    key: tuple[str, ...]
    partition: tuple[str, ...]  # path columns, before year=
    year_of: str | None  # the date column that sets year=; None when not by year

    @property
    def file_schema(self) -> pa.Schema:
        return pa.schema([f for f in self.schema if f.name not in self.partition])


DRAWS = Table(
    "draws",
    pa.schema(
        [
            *_DRAW,
            pa.field("draw_number", pa.int32()),
            pa.field("next_draw_text", pa.string()),
            pa.field("next_draw_date", pa.date32()),
            pa.field("started_local", _LOCAL_TIME),
            pa.field("first_ball_local", _LOCAL_TIME),
            pa.field("ended_local", _LOCAL_TIME),
            pa.field("timezone", pa.string(), nullable=False),
            pa.field("cross_source_check", pa.string(), nullable=False),
            _FLAGS,
            *LINEAGE,
        ]
    ),
    key=("country", "operator", "game", "draw_date"),
    partition=("country", "game"),
    year_of="draw_date",
)
DRAW_NUMBERS = Table(
    "draw_numbers",
    pa.schema(
        [
            *_DRAW,
            pa.field("ball_type", pa.string(), nullable=False),
            pa.field("position", pa.int32(), nullable=False),
            pa.field("is_draw_order", pa.bool_(), nullable=False),
            pa.field("number", pa.string(), nullable=False),
            pa.field("is_replacement", pa.bool_()),
            *LINEAGE,
        ]
    ),
    key=("country", "operator", "game", "draw_date", "ball_type", "position"),
    partition=("country", "game"),
    year_of="draw_date",
)
PRIZES = Table(
    "prizes",
    pa.schema(
        [
            *_DRAW,
            pa.field("prize", pa.string(), nullable=False),
            pa.field("pool_amount", pa.decimal128(18, 2)),
            pa.field("currency", pa.string(), nullable=False),
            pa.field("winners_status", pa.string(), nullable=False),
            pa.field("winning_coupons", pa.int32()),
            _FLAGS,
            *LINEAGE,
        ]
    ),
    key=("country", "operator", "game", "draw_date", "prize"),
    partition=("country", "game"),
    year_of="draw_date",
)
# A draw that does not parse goes here whole, never half in silver (PR-044). ``game`` is
# null when the whole page went (a ver_resultados that does not parse takes every game of the
# day), so the partition has no game=. Bronze keeps the page: nothing of it is copied.
QUARANTINE = Table(
    "quarantine",
    pa.schema(
        [
            pa.field("country", pa.string(), nullable=False),
            pa.field("operator", pa.string(), nullable=False),
            pa.field("source", pa.string(), nullable=False),
            pa.field("draw_date", pa.date32(), nullable=False),
            pa.field("game", pa.string()),
            pa.field("reason", pa.string(), nullable=False),
            *LINEAGE,
        ]
    ),
    key=("country", "source", "draw_date", "game"),
    partition=("country",),
    year_of="draw_date",
)
# The reference tables: the CSVs of sorteos/<country>/reference/ as they are, plus country and
# operator. Their dates are typed; an empty cell is null.
GAME_RULES = Table(
    "game_rules",
    pa.schema(
        [
            pa.field("country", pa.string(), nullable=False),
            pa.field("operator", pa.string(), nullable=False),
            pa.field("game", pa.string(), nullable=False),
            pa.field("rule", pa.string(), nullable=False),
            pa.field("value", pa.string()),
            pa.field("valid_from", pa.date32()),
            pa.field("valid_to", pa.date32()),
            pa.field("source", pa.string()),
            pa.field("source_url", pa.string()),
            pa.field("evidence", pa.string()),
            *LINEAGE,
        ]
    ),
    key=("country", "game", "rule", "valid_from"),
    partition=("country",),
    year_of=None,
)
CALENDAR_EVENTS = Table(
    "calendar_events",
    pa.schema(
        [
            pa.field("country", pa.string(), nullable=False),
            pa.field("operator", pa.string(), nullable=False),
            pa.field("event_date", pa.date32(), nullable=False),
            pa.field("games", pa.string(), nullable=False),
            pa.field("event_type", pa.string(), nullable=False),
            pa.field("moved_to", pa.date32()),
            pa.field("cause", pa.string()),
            pa.field("source_url", pa.string()),
            pa.field("check_manifest", pa.string()),
            pa.field("origin", pa.string()),
            *LINEAGE,
        ]
    ),
    key=("country", "event_date", "games"),
    partition=("country",),
    year_of=None,
)
# The gap detector's output (D13): one row per expected draw that did not come. Not by year:
# it is rewritten whole every run, from every year of ``draws`` (owner, UY-028 2a), because a
# gap can start in December and end in January. Its lineage is the draw whose expectation
# failed.
DRAW_GAPS = Table(
    "draw_gaps",
    pa.schema(
        [
            pa.field("country", pa.string(), nullable=False),
            pa.field("operator", pa.string(), nullable=False),
            pa.field("game", pa.string(), nullable=False),
            pa.field("previous_draw_date", pa.date32(), nullable=False),
            pa.field("expected_date", pa.date32(), nullable=False),
            pa.field("expected_from", pa.string(), nullable=False),
            pa.field("window_end", pa.date32(), nullable=False),
            pa.field("next_draw_date", pa.date32()),
            pa.field("status", pa.string(), nullable=False),
            pa.field("calendar_event_date", pa.date32()),
            *LINEAGE,
        ]
    ),
    key=("country", "operator", "game", "previous_draw_date"),
    partition=("country",),
    year_of=None,
)
TABLES = {
    t.name: t
    for t in (DRAWS, DRAW_NUMBERS, PRIZES, QUARANTINE, GAME_RULES, CALENDAR_EVENTS, DRAW_GAPS)
}
_LINEAGE_NAMES = frozenset(f.name for f in LINEAGE)


def utc_now() -> datetime:
    """The value for ``ingested_at``: UTC, naive, taken once per run."""
    return datetime.now(UTC).replace(tzinfo=None)


def parser_version(versions: Mapping[str, int]) -> str:
    """Every source that gave something to a row, the primary first (owner, UY-025 3a).

    ``{"resultados": 1, "pozos_5_de_oro": 1}`` → ``"resultados:1;pozos_5_de_oro:1"``.
    """
    if not versions:
        raise SilverError("a row comes from at least one source")
    for source, version in versions.items():
        if not source or ":" in source or ";" in source or isinstance(version, bool):
            raise SilverError(f"bad parser version {source!r}: {version!r}")
    return ";".join(f"{source}:{version}" for source, version in versions.items())


def partition_dir(root: Path, table: Table, values: Mapping[str, object], year: int | None) -> Path:
    path = root / table.name
    for column in table.partition:
        path /= f"{column}={values[column]}"
    return path / f"year={year}" if table.year_of else path


def check_rows(
    table: Table,
    rows: Sequence[Mapping[str, object]],
    *,
    country: str,
    year: int | None,
    flags: Mapping[str, str],
) -> None:
    """Raise ``SilverError`` on the first row that cannot be written as it is."""
    if (year is None) != (table.year_of is None):
        raise SilverError(f"{table.name}: year={year} for a table partitioned by {table.year_of}")
    columns = set(table.schema.names)
    required = [f.name for f in table.schema if not f.nullable]
    seen: set[tuple] = set()
    for i, row in enumerate(rows):
        where = f"{table.name} row {i}"
        if set(row) != columns:
            missing, extra = sorted(columns - set(row)), sorted(set(row) - columns)
            raise SilverError(f"{where}: missing {missing}, unknown {extra}")
        empty = [name for name in required if row[name] is None]
        if empty:
            raise SilverError(f"{where}: {empty} cannot be null")
        if row["country"] != country:
            raise SilverError(f"{where}: country {row['country']!r} in a write of {country!r}")
        when = row[table.year_of] if table.year_of else None
        if table.year_of and (not isinstance(when, date) or when.year != year):
            raise SilverError(f"{where}: {table.year_of} {when!r} in year={year}")
        if "dq_flags" in row:
            _check_flags(where, table, row["dq_flags"], flags)
        key = tuple(row[k] for k in table.key)
        if key in seen:
            raise SilverError(f"{where}: key {key} is repeated")
        seen.add(key)


def _check_flags(where: str, table: Table, values: object, flags: Mapping[str, str]) -> None:
    if not isinstance(values, list | tuple):
        raise SilverError(f"{where}: dq_flags must be a list, not {type(values).__name__}")
    if len(set(values)) != len(values):
        raise SilverError(f"{where}: dq_flags {values} repeats a flag")
    for flag in values:
        if flag not in flags:
            raise SilverError(f"{where}: {flag!r} is not in the dq_flags catalog (D22)")
        if flags[flag] != table.name:
            raise SilverError(f"{where}: {flag!r} belongs to {flags[flag]}, not {table.name}")


def write(
    root: Path,
    table: Table,
    rows: Sequence[Mapping[str, object]],
    *,
    country: str,
    year: int | None = None,
    flags: Mapping[str, str] | None = None,
) -> list[Path]:
    """Replace every partition of ``table`` for ``country`` and ``year`` with ``rows``.

    Returns the files written. Nothing is touched if a row fails its checks. Each file is
    written beside its final name and moved into place, so a crash never leaves half a file.
    """
    check_rows(table, rows, country=country, year=year, flags=flags or {})
    groups: dict[Path, list[Mapping[str, object]]] = {}
    for row in rows:
        groups.setdefault(partition_dir(root, table, row, year), []).append(row)
    tables = {}
    for directory, members in groups.items():
        members = sorted(members, key=lambda r: [_sortable(r[k]) for k in table.key])
        records = [_for_file(table, r) for r in members]
        try:
            tables[directory] = pa.Table.from_pylist(records, schema=table.file_schema)
        except (pa.ArrowInvalid, pa.ArrowTypeError) as exc:
            raise SilverError(f"{table.name} {directory.relative_to(root)}: {exc}") from exc

    written = []
    for directory, data in tables.items():
        directory.mkdir(parents=True, exist_ok=True)
        tmp = directory / f".{FILE_NAME}.tmp"
        pq.write_table(data, tmp)
        os.replace(tmp, directory / FILE_NAME)
        written.append(directory / FILE_NAME)
    for stale in _partitions(root, table, country, year):
        if stale / FILE_NAME not in written:
            shutil.rmtree(stale)
    return written


def read(root: Path, table: Table, columns: Sequence[str] | None = None) -> list[dict]:
    """Every row of ``table`` under ``root``, the path columns typed as the schema says (left
    to pyarrow they come back as dictionaries). No files at all is no rows."""
    path = root / table.name
    if not path.is_dir() or not any(path.rglob(FILE_NAME)):
        return []
    fields = [table.schema.field(name) for name in table.partition]
    if table.year_of:
        fields.append(pa.field("year", pa.int32()))
    dataset = pads.dataset(
        path, format="parquet", partitioning=pads.partitioning(pa.schema(fields), flavor="hive")
    )
    rows = dataset.to_table(columns=list(columns) if columns else None).to_pylist()
    for row in rows:
        row.pop("year", None)
    return rows


def _partitions(root: Path, table: Table, country: str, year: int | None) -> list[Path]:
    """The partition folders of ``country`` and ``year`` that exist now."""
    base = root / table.name / f"country={country}"
    if not base.is_dir():
        return []
    pattern = "/".join(f"{c}=*" for c in table.partition[1:])
    if table.year_of:
        pattern = f"{pattern}/year={year}" if pattern else f"year={year}"
    return sorted(base.glob(pattern)) if pattern else [base]


def _for_file(table: Table, row: Mapping[str, object]) -> dict[str, object]:
    record = {k: v for k, v in row.items() if k not in table.partition}
    if "dq_flags" in record:
        record["dq_flags"] = sorted(record["dq_flags"])
    return record


def _sortable(value: object) -> tuple[bool, object]:
    return (value is not None, value if value is not None else "")


def read_reference(
    path: Path,
    table: Table,
    *,
    country: str,
    operator: str,
    ingested_at: datetime,
    run_id: str | None,
    source_key: str,
) -> list[dict[str, object]]:
    """The rows of a reference CSV, with its header checked against ``table``.

    Untransformed: dates become ``date`` and an empty cell becomes null, nothing else. There
    is no parser, so ``parser_version`` is null; ``source_sha256`` is the CSV's.
    """
    if table.year_of is not None:
        raise SilverError(f"{table.name} is not a reference table")
    content = path.read_bytes()
    reader = csv.DictReader(content.decode("utf-8").splitlines())
    expected = [n for n in table.schema.names if n not in {"country", "operator"} | _LINEAGE_NAMES]
    if reader.fieldnames != expected:
        raise SilverError(f"{path.name}: header {reader.fieldnames}, expected {expected}")
    dates = {f.name for f in table.schema if f.type == pa.date32()}
    lineage = {
        "ingested_at": ingested_at,
        "run_id": run_id,
        "source_key": source_key,
        "source_sha256": hashlib.sha256(content).hexdigest(),
        "parser_version": None,
    }
    rows = []
    for line, cells in enumerate(reader, start=2):
        row: dict[str, object] = {"country": country, "operator": operator}
        for name, cell in cells.items():
            if name is None or cell is None:
                raise SilverError(f"{path.name} line {line}: not {len(expected)} cells")
            text = cell.strip()
            try:
                row[name] = (date.fromisoformat(text) if name in dates else text) if text else None
            except ValueError as exc:
                raise SilverError(f"{path.name} line {line}: {name} {text!r}") from exc
        rows.append(row | lineage)
    return rows
