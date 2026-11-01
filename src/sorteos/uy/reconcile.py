"""The reconciliation report of local UY silver (UY-030; roadmap Fase 4). Reads silver only.

    python -m sorteos.uy.reconcile                       # markdown to stdout
    python -m sorteos.uy.reconcile --json-report months.json

What it reconciles, each against something it did not come from:

- **The calendar**, per game, year and month: every weekday of the game's YAML calendar has a
  draw or a reason not to (``core.reconcile``), and those weekdays are counted again from the
  dates alone. A gap is ``explained`` by a ``calendar_events`` row or stays ``open``.
- **``draw_gaps``**, recomputed from ``draws`` today: the table in silver must be the same.
  It is not when silver was written before a window closed; ``make uy-silver`` rewrites it.
- **The draw number**, per game that has one: from the first numbered draw on, each is the
  previous plus one, except on the draws flagged ``draw_number_out_of_sequence`` (UY-024).
- **Quarantine**: its rows, against the draws that made it to silver.

The exit code is 1 when any of them fails: a calendar day without a reason, an open gap, a
stale ``draw_gaps``, an unflagged break in the draw number, or anything in quarantine.
``ver_estadisticas`` joins it in UY-030.2.
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
from sorteos.core import reconcile as rc
from sorteos.core import silver as core_silver
from sorteos.uy import backfill, build_silver, silver
from sorteos.uy import dq_flags as dq

DRAW_COLUMNS = (*silver.GAP_INPUTS, "draw_number", "dq_flags")
GAP_KEY = ("game", "previous_draw_date", "expected_date", "status", "calendar_event_date")


@dataclass
class Game:
    name: str
    days: list[rc.Day]
    months: dict[tuple[int, int], Counter]
    weekdays_counted: int  # calendar weekdays from the first draw to the last day accounted

    @property
    def totals(self) -> Counter:
        return sum(self.months.values(), Counter())

    def years(self) -> dict[int, Counter]:
        out: dict[int, Counter] = defaultdict(Counter)
        for (year, _), counts in self.months.items():
            out[year] += counts
        return dict(sorted(out.items()))


@dataclass
class Series:
    game: str
    first: dict  # the first numbered draw
    last: dict
    numbered: int
    inferred: int
    missing: list[date]  # draws without a number after the first numbered one
    steps: Counter  # difference between consecutive numbered draws -> how many
    breaks: list[tuple[dict, dict]]  # consecutive numbered draws whose difference is not 1


@dataclass
class Reconciliation:
    today: date
    games: list[Game] = field(default_factory=list)
    gaps: list[dict] = field(default_factory=list)  # draw_gaps as silver has it
    events: dict[date, list[dict]] = field(default_factory=dict)
    stale_gaps: list[str] = field(default_factory=list)
    series: list[Series] = field(default_factory=list)
    quarantine: Counter = field(default_factory=Counter)  # per "source: reason"
    draws: int = 0

    @property
    def problems(self) -> list[str]:
        out = []
        for g in self.games:
            accounted = g.totals["calendar"]
            if accounted != g.weekdays_counted:
                out.append(
                    f"{g.name}: {accounted} calendar weekdays accounted for, "
                    f"{g.weekdays_counted} counted from the dates"
                )
            if g.totals[rc.GAP_OPEN]:
                out.append(f"{g.name}: {g.totals[rc.GAP_OPEN]} calendar days in open gaps")
        out += [f"draw_gaps is stale: {line}" for line in self.stale_gaps]
        for s in self.series:
            out += [f"{s.game}: no draw number on {day}" for day in s.missing]
            out += [
                f"{s.game}: {a['draw_number']} on {a['draw_date']} then {b['draw_number']} "
                f"on {b['draw_date']}, not flagged {dq.DRAW_NUMBER_OUT_OF_SEQUENCE}"
                for a, b in s.breaks
                if dq.DRAW_NUMBER_OUT_OF_SEQUENCE not in b["dq_flags"]
            ]
        if self.quarantine:
            out.append(f"quarantine: {sum(self.quarantine.values())} rows")
        return out


def collect(root: Path, today: date) -> Reconciliation:
    report = Reconciliation(today)
    draws = core_silver.read(root, core_silver.DRAWS, DRAW_COLUMNS)
    events = core_silver.read(root, core_silver.CALENDAR_EVENTS)
    report.draws = len(draws)
    for e in events:
        report.events.setdefault(e["event_date"], []).append(e)
    by_game: dict[str, list[dict]] = defaultdict(list)
    for row in sorted(draws, key=lambda r: (r["game"], r["draw_date"])):
        by_game[row["game"]].append(row)
    for name, rows in sorted(by_game.items()):
        weekdays = silver.CONFIG.games[name].calendar.weekdays
        days = rc.account(
            [gaps.Draw(r["draw_date"], r["next_draw_date"]) for r in rows],
            weekdays,
            [e["event_date"] for e in events if name in silver.games_of(e)],
            today,
        )
        counted = rc.calendar_weekdays(days[0].day, days[-1].day, weekdays)
        report.games.append(Game(name, days, rc.month_counts(days), counted))
        series = draw_number_series(name, rows)
        if series:
            report.series.append(series)

    report.gaps = sorted(
        core_silver.read(root, core_silver.DRAW_GAPS), key=lambda r: (r["game"], r["expected_date"])
    )
    run = silver.Run(datetime(1970, 1, 1))  # nothing is written: the lineage is not kept
    fresh = silver.gap_rows(draws, events, run, today)
    stored = {tuple(r[k] for k in GAP_KEY) for r in report.gaps}
    computed = {tuple(r[k] for k in GAP_KEY) for r in fresh}
    report.stale_gaps = [f"only in silver: {k}" for k in sorted(stored - computed, key=str)] + [
        f"only recomputed: {k}" for k in sorted(computed - stored, key=str)
    ]

    for row in core_silver.read(root, core_silver.QUARANTINE, ["source", "reason"]):
        report.quarantine[f"{row['source']}: {row['reason']}"] += 1
    return report


def draw_number_series(game: str, rows: list[dict]) -> Series | None:
    """The draw number from the first draw that has one; None for a game that has none."""
    start = next((i for i, r in enumerate(rows) if r["draw_number"] is not None), None)
    if start is None:
        return None
    rows = rows[start:]
    numbered = [r for r in rows if r["draw_number"] is not None]
    pairs = list(zip(numbered, numbered[1:], strict=False))
    return Series(
        game,
        numbered[0],
        numbered[-1],
        len(numbered),
        sum(dq.DRAW_NUMBER_INFERRED in r["dq_flags"] for r in numbered),
        [r["draw_date"] for r in rows if r["draw_number"] is None],
        Counter(b["draw_number"] - a["draw_number"] for a, b in pairs),
        [(a, b) for a, b in pairs if b["draw_number"] - a["draw_number"] != 1],
    )


# --- the report ---------------------------------------------------------------------------

_YEAR_COLUMNS = (
    ("draws", "draws"),
    ("calendar", "calendar"),
    ("on calendar", rc.ON_CALENDAR),
    ("skipped", rc.SKIPPED),
    ("moved", rc.MOVED),
    ("gap (explained)", rc.GAP_EXPLAINED),
    ("gap (open)", rc.GAP_OPEN),
    ("off: announced", rc.OFF_CALENDAR_ANNOUNCED),
    ("off: moved", rc.OFF_CALENDAR_MOVED),
    ("off: other", rc.OFF_CALENDAR_OTHER),
)


def _table(header: list[str], rows: list[list[object]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return lines


def format_report(r: Reconciliation) -> str:
    lines = [f"# UY reconciliation — {r.today}", ""]
    problems = r.problems
    lines += [f"**Result: {'FAILED' if problems else 'ok'}**", ""]
    lines += [f"- {p}" for p in problems] + ([""] if problems else [])

    lines += ["## Calendar", ""]
    lines += _table(
        ["game", "first draw", "last day", *(h for h, _ in _YEAR_COLUMNS), "weekdays counted"],
        [
            [
                g.name,
                g.days[0].day,
                g.days[-1].day,
                *(g.totals[k] for _, k in _YEAR_COLUMNS),
                g.weekdays_counted,
            ]
            for g in r.games
        ],
    )
    for g in r.games:
        lines += ["", f"### {g.name} per year", ""]
        lines += _table(
            ["year", *(h for h, _ in _YEAR_COLUMNS)],
            [[year, *(c[k] for _, k in _YEAR_COLUMNS)] for year, c in g.years().items()],
        )
        odd = [
            d for d in g.days if d.kind in (rc.GAP_EXPLAINED, rc.GAP_OPEN, rc.OFF_CALENDAR_OTHER)
        ]
        if odd:
            lines += ["", "Days in a gap or off the calendar for another reason:", ""]
            lines += [f"- {d.day} ({d.day:%a}): {d.kind}" for d in odd]

    lines += ["", "## draw_gaps", ""]
    if r.gaps:
        lines += _table(
            ["game", "previous draw", "expected", "from", "next draw", "status", "event"],
            [
                [
                    g["game"],
                    g["previous_draw_date"],
                    g["expected_date"],
                    g["expected_from"],
                    g["next_draw_date"] or "none yet",
                    g["status"],
                    _event(r, g["game"], g["calendar_event_date"]),
                ]
                for g in r.gaps
            ],
        )
    else:
        lines.append("No gaps.")
    if r.stale_gaps:
        lines += ["", "Differs from a recomputation today (run `make uy-silver`):", ""]
        lines += [f"- {s}" for s in r.stale_gaps]

    lines += ["", "## Draw number", ""]
    for s in r.series:
        lines += [
            f"**{s.game}**: {s.first['draw_number']} on {s.first['draw_date']} to "
            f"{s.last['draw_number']} on {s.last['draw_date']}: {s.numbered} numbered draws "
            f"({s.numbered - s.inferred} read, {s.inferred} inferred), "
            f"{len(s.missing)} without a number",
            "",
            "Steps between consecutive draws: "
            + ", ".join(f"{n}× {step:+d}" for step, n in sorted(s.steps.items())),
        ]
        if s.breaks:
            lines += [""]
            lines += [
                f"- {a['draw_date']} {a['draw_number']} → {b['draw_date']} {b['draw_number']} "
                f"{sorted(b['dq_flags'])}"
                for a, b in s.breaks
            ]
    if not r.series:
        lines.append("No game has a draw number.")

    rows = sum(r.quarantine.values())
    lines += ["", "## Quarantine", ""]
    lines.append(
        f"{rows} rows against {r.draws} draws in silver "
        f"({100 * rows / (r.draws + rows):.2f} %)."
        if r.draws + rows
        else "Silver is empty."
    )
    lines += [f"- {n} {why}" for why, n in sorted(r.quarantine.items())]
    return "\n".join(lines) + "\n"


def _event(r: Reconciliation, game: str, day: date | None) -> str:
    if day is None:
        return "—"
    found = [e for e in r.events.get(day, []) if game in silver.games_of(e)]
    return f"{day}: " + "; ".join(f"{e['event_type']} ({e['cause'] or 'no cause'})" for e in found)


def months_json(r: Reconciliation) -> dict:
    return {
        g.name: {f"{y}-{m:02d}": dict(c) for (y, m), c in sorted(g.months.items())} for g in r.games
    }


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m sorteos.uy.reconcile",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--silver", type=Path, default=build_silver.DEFAULT_SILVER)
    p.add_argument("--json-report", type=Path, help="also write the counts per month as JSON")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = collect(args.silver, backfill.today_in_uruguay())
    sys.stdout.write(format_report(report))
    if args.json_report:
        args.json_report.write_text(
            json.dumps(months_json(report), indent=2, sort_keys=True) + "\n"
        )
    return 1 if report.problems else 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
