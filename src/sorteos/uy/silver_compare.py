"""Reconcile the cloud's UY silver with a local build, row by row (UY-042.4.2; roadmap UY-042).

    python -m sorteos.uy.silver_compare --root data/uy \\
        --bucket lottery-partitioned-storage-prod [--prefix uy/silver/]

**Against what (owner, UY-042.4.2 2a).** A local silver built NOW, with today's code, from the
local manifest (SQLite) and bronze on disk, into a temporary folder: the very steps of
``make uy-silver``. ``data/uy/silver`` is not touched. SQLite and the DynamoDB table must hold
the same manifest (``make uy-manifest-check``), so any difference comes from the cloud run.

**How.** Every table of ``core.silver.TABLES``, read with ``core.silver.read`` on both sides.
Rows are matched by the table's key. Every column is compared except the two that change on
every run by design: ``ingested_at`` and ``run_id``. The lineage that matters, ``source_key``,
``source_sha256`` and ``parser_version``, must be equal. Each table also gets a digest of all
its rows on each side, so the report states the match in one line.

``draw_gaps`` depends on the date in Uruguay (an open window is still open today), so run this
on the day of the cloud's ``finalize``.

The exit code is 0 when every table matches, 1 when any differs.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from sorteos.core import manifest as mf
from sorteos.core import silver as core_silver
from sorteos.core.bronze import BronzeStore
from sorteos.uy import backfill, build_silver
from sorteos.uy.sources import COUNTRY

RUN_COLUMNS = frozenset({"ingested_at", "run_id"})
SHOW = 10

Key = tuple


def canonical(value: object) -> object:
    """Lists become tuples, so a row can be hashed and a list in a key can be matched."""
    if isinstance(value, list | tuple):
        return tuple(canonical(v) for v in value)
    return value


def comparable(row: Mapping[str, object]) -> dict[str, object]:
    return {k: canonical(v) for k, v in row.items() if k not in RUN_COLUMNS}


def digest(rows: Sequence[Mapping[str, object]]) -> str:
    lines = sorted(repr(sorted(r.items())) for r in rows)
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()[:16]


@dataclass
class TableResult:
    name: str
    local: int = 0
    cloud: int = 0
    local_digest: str = ""
    cloud_digest: str = ""
    missing: list[Key] = field(default_factory=list)  # in local, not in the cloud
    extra: list[Key] = field(default_factory=list)  # in the cloud, not in local
    different: list[tuple[Key, list[str]]] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not (self.missing or self.extra or self.different or self.duplicates)


def _by_key(table: core_silver.Table, rows, side: str, result: TableResult) -> dict[Key, dict]:
    keyed: dict[Key, dict] = {}
    for row in rows:
        key = tuple(row[k] for k in table.key)
        if key in keyed:
            result.duplicates.append(f"{side}: {key}")
        keyed[key] = row
    return keyed


def compare_table(table: core_silver.Table, local_rows, cloud_rows) -> TableResult:
    local = [comparable(r) for r in local_rows]
    cloud = [comparable(r) for r in cloud_rows]
    result = TableResult(table.name, len(local), len(cloud), digest(local), digest(cloud))
    mine = _by_key(table, local, "local", result)
    theirs = _by_key(table, cloud, "cloud", result)
    result.missing = sorted(set(mine) - set(theirs), key=repr)
    result.extra = sorted(set(theirs) - set(mine), key=repr)
    for key in sorted(set(mine) & set(theirs), key=repr):
        columns = [c for c in mine[key] if mine[key][c] != theirs[key].get(c)]
        if columns:
            result.different.append((key, columns))
    return result


def compare(local_root: Path, cloud_root: Path) -> list[TableResult]:
    return [
        compare_table(
            table, core_silver.read(local_root, table), core_silver.read(cloud_root, table)
        )
        for table in core_silver.TABLES.values()
    ]


def render(results: list[TableResult]) -> str:
    lines = [f"{'table':<16} {'local':>8} {'cloud':>8}  digest (local = cloud)"]
    for r in results:
        same = r.local_digest == r.cloud_digest
        lines.append(
            f"{r.name:<16} {r.local:>8,} {r.cloud:>8,}  {r.local_digest}"
            + ("" if same else f" ≠ {r.cloud_digest}")
            + ("" if r.ok else "  DIFFERS")
        )
    for r in results:
        for title, items in (
            ("only local", r.missing),
            ("only in the cloud", r.extra),
            ("different", [f"{k}: {cols}" for k, cols in r.different]),
            ("repeated key", r.duplicates),
        ):
            if items:
                lines.append(
                    f"\n{r.name}, {title} ({len(items):,}, first {min(len(items), SHOW)}):"
                )
                lines.extend(f"  {item}" for item in items[:SHOW])
    ok = all(r.ok for r in results)
    lines.append(
        "\nOK: the cloud's silver is the local build, row by row (ingested_at and run_id aside)."
        if ok
        else "\nFAIL"
    )
    return "\n".join(lines)


def build_local(root: Path, out: Path) -> None:
    """``make uy-silver`` into ``out``: every year, then draw_gaps."""
    manifest = mf.SqliteManifest(root / "manifest.sqlite", backfill.load_overrides())
    try:
        run = build_silver.new_run("reconcile")
        years = build_silver.all_years(manifest)
        build_silver.rebuild(manifest, BronzeStore(root, COUNTRY), out, years, run)
        build_silver.detect_gaps(out, run, backfill.today_in_uruguay())
    finally:
        manifest.close()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m sorteos.uy.silver_compare",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--root", type=Path, required=True, help="data/uy: manifest.sqlite + bronze")
    p.add_argument("--bucket", required=True)
    p.add_argument("--prefix", default="uy/silver/")
    return p


def main(argv: list[str] | None = None, s3=None) -> int:
    args = build_parser().parse_args(argv)
    if not (args.root / "manifest.sqlite").is_file():
        print(f"{args.root} has no manifest.sqlite: is it data/uy?", file=sys.stderr)
        return 2
    if s3 is None:  # pragma: no cover - the tests pass a moto client
        import boto3

        s3 = boto3.client("s3")
    from sorteos.uy.lambda_silver import download_tree

    with tempfile.TemporaryDirectory(prefix="uy-reconcile-") as work:
        local, cloud = Path(work) / "local", Path(work) / "cloud"
        print("building local silver (every year, ~5 minutes)...", file=sys.stderr)
        build_local(args.root, local)
        print(f"downloading s3://{args.bucket}/{args.prefix}...", file=sys.stderr)
        download_tree(s3, args.bucket, args.prefix, cloud)
        results = compare(local, cloud)
    print(render(results))
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
