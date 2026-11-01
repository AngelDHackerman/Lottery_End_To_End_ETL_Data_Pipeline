"""Rewrite local UY silver from bronze, one year at a time (UY-027.1). No requests.

    python -m sorteos.uy.build_silver                     # every year the manifest has
    python -m sorteos.uy.build_silver --years 2016        # the pilot (UY-030)
    python -m sorteos.uy.build_silver --years 2014-2016,2026

Each year is rewritten whole, in the four tables, and the reference tables with it (D17), so a
second run gives the same rows. The draw-number series is built once per run across every year
(UY-025.3): rewriting a single year still reads all the pozos PDF (~10 s). The incremental
(``sorteos.uy.incremental``) calls ``rebuild()`` with the years it touched.

Then ``draw_gaps`` is rewritten whole, from every year of silver (D13), unless silver has
anything in quarantine: a draw in quarantine is missing from ``draws`` and would read as a
gap, so the table keeps its last version and the run exits 1 (owner, UY-028 3a).
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from sorteos.core import gaps
from sorteos.core import manifest as mf
from sorteos.core import silver as core_silver
from sorteos.core.bronze import BronzeStore
from sorteos.uy import backfill, silver
from sorteos.uy.parsers import resultados
from sorteos.uy.sources import COUNTRY

logger = logging.getLogger(__name__)

DEFAULT_SILVER = Path("data/uy/silver")


@dataclass
class YearCount:
    year: int
    draws: int = 0
    numbers: int = 0
    prizes: int = 0
    quarantine: int = 0
    flags: Counter = field(default_factory=Counter)
    seconds: float = 0.0  # build + write of the year: one item of UY-042's Map (D18)

    @classmethod
    def of(cls, year: int, rows: silver.YearRows, seconds: float = 0.0) -> YearCount:
        flags = Counter(
            flag
            for row in (*rows.draws, *rows.draw_numbers, *rows.prizes)
            for flag in row.get("dq_flags", ())
        )
        return cls(
            year,
            len(rows.draws),
            len(rows.draw_numbers),
            len(rows.prizes),
            len(rows.quarantine),
            flags,
            seconds,
        )


def new_run(kind: str) -> silver.Run:
    """One ``run_id`` per command, readable in the lineage: ``uy-silver-20261029T031500Z``."""
    now = core_silver.utc_now()
    return silver.Run(now, f"uy-{kind}-{now:%Y%m%dT%H%M%SZ}")


def all_years(manifest: mf.Manifest) -> list[int]:
    span = manifest.date_range(resultados.SOURCE)
    if span is None:
        return []
    return list(range(int(span[0][:4]), int(span[1][:4]) + 1))


def rebuild(
    manifest: mf.Manifest,
    bronze: BronzeStore,
    out: Path,
    years: Iterable[int],
    run: silver.Run,
) -> list[YearCount]:
    series = silver.number_series(manifest, bronze)
    counts = []
    for year in years:
        started = time.perf_counter()
        rows = silver.build_year(year, manifest, bronze, run, series)
        silver.write_year(out, year, rows)
        count = YearCount.of(year, rows, time.perf_counter() - started)
        counts.append(count)
        logger.info(
            "silver year written",
            extra={
                "year": year,
                "draws": count.draws,
                "quarantine": count.quarantine,
                "seconds": round(count.seconds, 1),
            },
        )
    silver.write_reference(out, run)
    return counts


@dataclass
class GapReport:
    rows: list[dict] | None  # None: not rewritten, because of the quarantine
    quarantine: int = 0


def detect_gaps(out: Path, run: silver.Run, today: date) -> GapReport:
    """Rewrite ``draw_gaps`` from the silver under ``out``, unless it has quarantine rows."""
    quarantine = len(core_silver.read(out, core_silver.QUARANTINE, ["reason"]))
    if quarantine:
        logger.warning("draw_gaps not rewritten", extra={"quarantine": quarantine})
        return GapReport(None, quarantine)
    rows = silver.write_gaps(out, run, today)
    logger.info(
        "draw_gaps written",
        extra={"gaps": len(rows), "open": sum(r["status"] == gaps.OPEN for r in rows)},
    )
    return GapReport(rows)


def format_gaps(report: GapReport) -> str:
    if report.rows is None:
        return f"draw_gaps: not rewritten, silver has {report.quarantine} rows in quarantine"
    status = Counter(r["status"] for r in report.rows)
    lines = [
        f"draw_gaps: {len(report.rows)} "
        f"({status[gaps.EXPLAINED]} explained, {status[gaps.OPEN]} open)"
    ]
    lines += [describe_open(r) for r in report.rows if r["status"] == gaps.OPEN]
    return "\n".join(lines)


def describe_open(row: dict) -> str:
    return (
        f"open {row['game']} expected {row['expected_date']} ({row['expected_from']}), "
        f"window closed {row['window_end']}, next draw {row['next_draw_date'] or 'none yet'}"
    )


def format_counts(counts: list[YearCount]) -> str:
    lines = [
        f"{'year':>4} {'draws':>7} {'numbers':>8} {'prizes':>7} {'quarantine':>10} {'seconds':>8}"
    ]
    total = YearCount(0)
    for c in counts:
        lines.append(
            f"{c.year:>4} {c.draws:>7} {c.numbers:>8} {c.prizes:>7} {c.quarantine:>10} "
            f"{c.seconds:>8.1f}"
        )
        total.draws += c.draws
        total.numbers += c.numbers
        total.prizes += c.prizes
        total.quarantine += c.quarantine
        total.flags += c.flags
        total.seconds += c.seconds
    lines.append(
        f"{'all':>4} {total.draws:>7} {total.numbers:>8} {total.prizes:>7} {total.quarantine:>10} "
        f"{total.seconds:>8.1f}"
    )
    if counts:
        slowest = max(counts, key=lambda c: c.seconds)
        lines.append(f"slowest year: {slowest.year}, {slowest.seconds:.1f} s")
    lines += [f"flag {name}: {n}" for name, n in sorted(total.flags.items())]
    return "\n".join(lines)


def parse_years(spec: str) -> list[int]:
    """``2016``, ``2014-2016`` or a comma list of both."""
    years: set[int] = set()
    for token in (t.strip() for t in spec.split(",") if t.strip()):
        first, _, last = token.partition("-")
        try:
            years.update(range(int(first), int(last or first) + 1))
        except ValueError:
            raise argparse.ArgumentTypeError(f"not a year or a range of years: {token!r}") from None
    if not years:
        raise argparse.ArgumentTypeError("no years given")
    return sorted(years)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m sorteos.uy.build_silver",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--root", type=Path, default=backfill.DEFAULT_ROOT)
    p.add_argument("--silver", type=Path, default=DEFAULT_SILVER)
    p.add_argument("--years", type=parse_years, default=None, help="default: every year")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    from loteria.common.logging_setup import configure_logging

    configure_logging("loteria-uy-silver")
    manifest = mf.SqliteManifest(args.root / "manifest.sqlite", backfill.load_overrides())
    try:
        years = args.years or all_years(manifest)
        bronze = BronzeStore(args.root, COUNTRY)
        run = new_run("silver")
        counts = rebuild(manifest, bronze, args.silver, years, run)
        report = detect_gaps(args.silver, run, backfill.today_in_uruguay())
        print(format_counts(counts), format_gaps(report), sep="\n", file=sys.stderr)
    finally:
        manifest.close()
    return 0 if report.rows is not None else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
