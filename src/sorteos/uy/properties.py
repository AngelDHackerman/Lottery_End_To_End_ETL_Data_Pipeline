"""The properties of the whole local bronze (UY-027.2, D23): every rule, every file, no requests.

    python -m sorteos.uy.properties
    python -m sorteos.uy.properties --json-report properties.json

It runs the silver transform over every year **in memory** (nothing is written) and reports
what the parser PRs used to measure by hand (UY-022 to UY-025): draws per game, quarantine
and why, ``cross_source_check``, the flags, Quiniela draws with a repeated number (D3), the
Tómbola's size and replacements (P7) and the draw-number series (UY-025.3). Paste its output
in any PR that changes a parser, like a Terraform plan: the CI does not have the bronze.

The exit code is 1 when anything went to quarantine, and only then (owner, UY-027 5a): every
parse failure ends there, whatever its source, and so does a draw whose numbers break the
shape of its YAML. A flag is a count, not a failure: the catalog says what each one marks.
A bronze file that is not what the manifest fetched stops the run, as it does in silver.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from sorteos.core import gaps
from sorteos.core import manifest as mf
from sorteos.core import silver as core_silver
from sorteos.core.bronze import BronzeStore
from sorteos.uy import backfill, build_silver, silver
from sorteos.uy import dq_flags as dq
from sorteos.uy.parsers import pozos_pdf
from sorteos.uy.sources import COUNTRY, ORO, QN, QV


@dataclass
class Report:
    draws: Counter = field(default_factory=Counter)  # per game
    numbers: int = 0
    prizes: int = 0
    quarantine: Counter = field(default_factory=Counter)  # per "source: reason"
    cross_source_check: Counter = field(default_factory=Counter)
    flags: Counter = field(default_factory=Counter)
    quiniela_with_repeats: int = 0
    tombola_sizes: Counter = field(default_factory=Counter)  # numbers per Tómbola -> draws
    tombola_replacements: int = 0  # P7, over the Tómbolas it applies to
    tombola_p7_draws: int = 0
    without_next_draw: int = 0
    draw_numbers: Counter = field(default_factory=Counter)  # read / inferred / null, since PDF
    gaps: Counter = field(default_factory=Counter)  # explained / open (D13)
    open_gaps: list[str] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return sum(self.quarantine.values()) > 0

    def add(self, rows: silver.YearRows) -> None:
        numbers: dict[tuple, list[dict]] = defaultdict(list)
        for row in rows.draw_numbers:
            numbers[(row["game"], row["draw_date"], row["ball_type"])].append(row)
        for draw in rows.draws:
            game, day = draw["game"], draw["draw_date"]
            self.draws[game] += 1
            self.cross_source_check[draw["cross_source_check"]] += 1
            self.without_next_draw += draw["next_draw_text"] is None
            if game in (QV, QN):
                quiniela = [r["number"] for r in numbers[(game, day, "quiniela")]]
                self.quiniela_with_repeats += len(set(quiniela)) < len(quiniela)
                tombola = numbers[(game, day, "tombola")]
                self.tombola_sizes[len(tombola)] += 1
                # The 31 Tómbolas of 2006 that are not endings of their Quiniela have no
                # meaningful replacement (P7); UY-025.2's 1,787 left them out too.
                if tombola and dq.TOMBOLA_NOT_FROM_QUINIELA not in draw["dq_flags"]:
                    self.tombola_p7_draws += 1
                    self.tombola_replacements += sum(bool(r["is_replacement"]) for r in tombola)
            elif day >= pozos_pdf.FIRST_DAY:  # the 5 de Oro, since the first pozos PDF
                if draw["draw_number"] is None:
                    self.draw_numbers["null"] += 1
                elif "draw_number_inferred" in draw["dq_flags"]:
                    self.draw_numbers["inferred"] += 1
                else:
                    self.draw_numbers["read"] += 1
        for row in (*rows.draws, *rows.prizes):
            self.flags.update(row["dq_flags"])
        self.numbers += len(rows.draw_numbers)
        self.prizes += len(rows.prizes)
        for row in rows.quarantine:
            self.quarantine[f"{row['source']}: {row['reason']}"] += 1


def collect(manifest: mf.Manifest, bronze: BronzeStore, today: date | None = None) -> Report:
    """Every year in memory, then the gap detector over all of them, as silver would run it."""
    report = Report()
    years = build_silver.all_years(manifest)
    if not years:
        return report
    run = silver.Run(datetime(1970, 1, 1))  # nothing is written: the lineage is not kept
    series = silver.number_series(manifest, bronze)
    draws = []
    for year in years:
        rows = silver.build_year(year, manifest, bronze, run, series)
        report.add(rows)
        draws += rows.draws
    events = silver.reference_rows(core_silver.CALENDAR_EVENTS, run)
    for row in silver.gap_rows(draws, events, run, today or backfill.today_in_uruguay()):
        report.gaps[row["status"]] += 1
        if row["status"] == gaps.OPEN:
            report.open_gaps.append(build_silver.describe_open(row))
    return report


def _pct(part: int, whole: int) -> str:
    return f"{100 * part / whole:.1f} %" if whole else "-"


def format_report(report: Report) -> str:
    quiniela = report.draws[QV] + report.draws[QN]
    lines = [
        f"draws: {sum(report.draws.values())} "
        f"({report.draws[QN]} N, {report.draws[QV]} V, {report.draws[ORO]} 5 de Oro)",
        f"numbers: {report.numbers}, prizes: {report.prizes}",
        f"quarantine: {sum(report.quarantine.values())}",
        *(f"  {n:>5}  {why}" for why, n in sorted(report.quarantine.items())),
        "cross_source_check: "
        + ", ".join(f"{n} {k}" for k, n in sorted(report.cross_source_check.items())),
        *(f"flag {name}: {n}" for name, n in sorted(report.flags.items())),
        f"quiniela with a repeated number: {report.quiniela_with_repeats} of {quiniela} "
        f"({_pct(report.quiniela_with_repeats, quiniela)})",
        "tombola sizes: "
        + ", ".join(f"{n} with {size}" for size, n in sorted(report.tombola_sizes.items())),
        f"tombola replacements: {report.tombola_replacements / report.tombola_p7_draws:.3f} "
        f"per draw, over {report.tombola_p7_draws} (P7)"
        if report.tombola_p7_draws
        else "tombola replacements: -",
        f"without a next draw: {report.without_next_draw}",
        "5 de Oro draw number since the first pozos PDF: "
        + ", ".join(f"{n} {k}" for k, n in sorted(report.draw_numbers.items())),
        f"draw_gaps: {sum(report.gaps.values())} "
        f"({report.gaps[gaps.EXPLAINED]} explained, {report.gaps[gaps.OPEN]} open)",
        *report.open_gaps,
        f"result: {'FAILED (quarantine)' if report.failed else 'ok'}",
    ]
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m sorteos.uy.properties",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--root", type=Path, default=backfill.DEFAULT_ROOT)
    p.add_argument("--json-report", type=Path, help="also write the counts as JSON")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    manifest = mf.SqliteManifest(args.root / "manifest.sqlite", backfill.load_overrides())
    try:
        report = collect(manifest, BronzeStore(args.root, COUNTRY))
    finally:
        manifest.close()
    print(format_report(report), file=sys.stderr)
    if args.json_report:
        # Not dataclasses.asdict(): it rebuilds a Counter from its items, counting the pairs.
        counts = {k: dict(v) if isinstance(v, Counter) else v for k, v in vars(report).items()}
        args.json_report.write_text(json.dumps(counts, indent=2, sort_keys=True) + "\n")
    return 1 if report.failed else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
