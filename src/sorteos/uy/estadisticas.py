"""The DNLQ's own counts, ``ver_estadisticas.php``, against local silver (UY-030.2).

    python -m sorteos.uy.estadisticas            # ~12 POSTs, into bronze; then compares

The site counts how many times each number came out in a date range. Its form is the only
official figure that our silver can be checked against without coming from the same pages,
so ``uy-reconcile`` compares the two. What the form allows decides what is asked (FINDINGS,
Q10 and UY-030.2), and only values its interface offers are sent (owner, UY-030 6a):

- **5 de Oro** (``xjue=4``): the 5 numbers of the 5 de Oro and of the Revancha, never the
  extra ball, from 2006-01-01.
- **Quiniela** (``xjue=2``): the **Vespertina only** (verified on 2025: 0 differences against
  the Vespertina, hundreds against the Nocturna), from 2007-01-01, the first year it offers.
  One query per position it offers alone (1-6, 10, 15, 20) and one for 1 to 20. The Nocturna
  has no counterpart in the form (owner, UY-030 7a).
- **Tómbola** (``xjue=3``): from 2007-01-01, no positions.

Each query ends on the last draw that silver has of its game, so a comparison never depends
on when it is read. Every answer is kept in bronze as served, beside a ``queries.json`` that
says what was asked and what came back (owner, UY-030 8a). This module is the only one that
sends these requests; ``uy-reconcile`` reads the newest set from bronze.

One difference is known and explained (owner, UY-030 9a): the site's database also holds the
Revancha of 2010-11-07 under 2010-10-07, a Thursday without a draw (FINDINGS, Q10).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from sorteos.core import silver as core_silver
from sorteos.core.bronze import BronzeStore
from sorteos.core.http_client import PoliteClient
from sorteos.uy import backfill, build_silver, privacy
from sorteos.uy.parsers import estadisticas as parser
from sorteos.uy.sources import CONFIG, COUNTRY, ORO, QV

SOURCE = "estadisticas"
PATH = "/ver_estadisticas.php"
INDEX = "queries.json"
#: The positions the Quiniela form offers in its two selects (FINDINGS, UY-030.2).
POSITIONS = (1, 2, 3, 4, 5, 6, 10, 15, 20)


@dataclass(frozen=True)
class Query:
    name: str  # the file stem in bronze
    xjue: int
    game: str  # of silver
    grids: dict[str, str]  # grid title on the page -> ball_type in silver
    start: date
    end: date
    positions: tuple[int, int] | None = None  # Quiniela only: (from, to), both included

    @property
    def url(self) -> str:
        return f"{CONFIG.site.base_url}{PATH}?xjue={self.xjue}&xpos=1"

    @property
    def form(self) -> dict[str, str]:
        # The day without zeros and the month with them, as the form's own options are.
        form = {
            "xdia": str(self.start.day),
            "xmes": f"{self.start.month:02d}",
            "xano": str(self.start.year),
            "hdia": str(self.end.day),
            "hmes": f"{self.end.month:02d}",
            "hano": str(self.end.year),
        }
        if self.positions:
            form["xdes"], form["xhas"] = map(str, self.positions)
        return form


def queries(last_draw: dict[str, date]) -> list[Query]:
    """What is asked, given the last draw silver has of each game."""
    out = []
    if ORO in last_draw:
        out.append(Query("5_de_oro", 4, ORO, dict(parser.TITLES), date(2006, 1, 1), last_draw[ORO]))
    if QV in last_draw:
        start, end = date(2007, 1, 1), last_draw[QV]
        quiniela = {parser.UNTITLED: "quiniela"}
        for a, b in [*((p, p) for p in POSITIONS), (1, 20)]:
            out.append(Query(f"quiniela_pos{a:02d}-{b:02d}", 2, QV, quiniela, start, end, (a, b)))
        out.append(Query("tombola", 3, QV, {parser.UNTITLED: "tombola"}, start, end))
    return out


# --- bronze ------------------------------------------------------------------------------


def set_prefix(fetched_on: date) -> str:
    return f"bronze/country={COUNTRY}/source={SOURCE}/fetched={fetched_on.isoformat()}"


def fetch(
    client: PoliteClient, bronze: BronzeStore, asked: Iterable[Query], fetched_on: date
) -> list[dict]:
    """POST every query, keep each answer as served and write the index last."""
    prefix = set_prefix(fetched_on)
    index = []
    for q in asked:
        result = client.post(q.url, q.form)
        key = f"{prefix}/{q.name}.html"
        bronze.write(key, result.content)
        index.append(
            {
                "name": q.name,
                "xjue": q.xjue,
                "url": q.url,
                "form": q.form,
                "game": q.game,
                "grids": q.grids,
                "start": q.start.isoformat(),
                "end": q.end.isoformat(),
                "positions": list(q.positions) if q.positions else None,
                "status": result.status,
                "bytes": len(result.content),
                "content_sha256": hashlib.sha256(result.content).hexdigest(),
                "fetched_at": result.fetched_at.isoformat(),
                "bronze_key": key,
            }
        )
    bronze.write(f"{prefix}/{INDEX}", (json.dumps(index, indent=2) + "\n").encode())
    return index


@dataclass(frozen=True)
class Answer:
    query: Query
    status: int
    stats: parser.Stats | None  # None when the page could not be read
    error: str | None = None


def latest(bronze: BronzeStore) -> tuple[str, list[Answer]] | None:
    """The newest complete set in bronze (one with its index), read back; None if none."""
    base = bronze.root / f"bronze/country={COUNTRY}/source={SOURCE}"
    sets = sorted(p for p in base.glob("fetched=*") if (p / INDEX).is_file())
    if not sets:
        return None
    answers = []
    for row in json.loads((sets[-1] / INDEX).read_text()):
        q = Query(
            row["name"],
            row["xjue"],
            row["game"],
            row["grids"],
            date.fromisoformat(row["start"]),
            date.fromisoformat(row["end"]),
            tuple(row["positions"]) if row["positions"] else None,
        )
        content = bronze.read(row["bronze_key"])
        if hashlib.sha256(content).hexdigest() != row["content_sha256"]:
            answers.append(Answer(q, row["status"], None, "bronze is not what was fetched"))
            continue
        try:
            answers.append(Answer(q, row["status"], parser.parse(content)))
        except parser.StatsError as exc:
            answers.append(Answer(q, row["status"], None, str(exc)))
    return sets[-1].name.removeprefix("fetched="), answers


# --- the comparison ----------------------------------------------------------------------


@dataclass(frozen=True)
class Known:
    """A difference the site has and silver must not copy, with where it was found."""

    xjue: int
    day: date
    ball_type: str
    numbers: tuple[str, ...]
    consulted: int  # what it adds to "sorteos consultados"
    why: str


KNOWN = (
    Known(
        4,
        date(2010, 10, 7),
        "revancha",
        ("06", "08", "13", "40", "44"),
        1,
        "FINDINGS Q10: the Revancha of 2010-11-07 also stored under 2010-10-07",
    ),
)


@dataclass
class Comparison:
    query: Query
    consulted: tuple[int, int]  # (site, silver + known)
    differences: dict[str, dict[str, tuple[int, int]]] = field(default_factory=dict)
    known: list[Known] = field(default_factory=list)
    numbers: int = 0  # times counted on the site, every grid
    error: str | None = None

    @property
    def ok(self) -> bool:
        return (
            self.error is None
            and self.consulted[0] == self.consulted[1]
            and not any(self.differences.values())
        )


def compare(answer: Answer, draws: list[dict], numbers: list[dict]) -> Comparison:
    """One answer against silver's ``draws`` and ``draw_numbers`` (all games, all dates)."""
    q = answer.query
    if answer.error or answer.status != 200:
        return Comparison(q, (0, 0), error=answer.error or f"HTTP {answer.status}")

    def inside(row) -> bool:
        return row["game"] == q.game and q.start <= row["draw_date"] <= q.end

    expected = {ball: Counter() for ball in q.grids.values()}
    for row in numbers:
        if row["ball_type"] in expected and inside(row):
            if q.positions and not q.positions[0] <= row["position"] <= q.positions[1]:
                continue
            expected[row["ball_type"]][row["number"]] += 1
    consulted = sum(inside(row) for row in draws) * len(q.grids)

    known = [k for k in KNOWN if k.xjue == q.xjue and q.start <= k.day <= q.end]
    for k in known:
        expected[k.ball_type].update(k.numbers)
        consulted += k.consulted

    found = Comparison(q, (answer.stats.consulted, consulted), known=known)
    for title, ball in q.grids.items():
        site = answer.stats.grids.get(title, Counter())
        found.numbers += sum(site.values())
        found.differences[ball] = {
            n: (site[n], expected[ball][n])
            for n in sorted(set(site) | set(expected[ball]))
            if site[n] != expected[ball][n]
        }
    return found


def compare_latest(bronze: BronzeStore, silver_root: Path) -> tuple[str, list[Comparison]] | None:
    found = latest(bronze)
    if found is None:
        return None
    fetched, answers = found
    draws = core_silver.read(silver_root, core_silver.DRAWS, ["game", "draw_date"])
    numbers = core_silver.read(
        silver_root,
        core_silver.DRAW_NUMBERS,
        ["game", "draw_date", "ball_type", "position", "number"],
    )
    return fetched, [compare(a, draws, numbers) for a in answers]


def describe(c: Comparison) -> list[str]:
    q = c.query
    where = f"positions {q.positions[0]}-{q.positions[1]}" if q.positions else "all"
    head = f"{q.name} ({q.start} to {q.end}, {where})"
    if c.error:
        return [f"{head}: {c.error}"]
    lines = [
        f"{head}: {c.consulted[0]} draws consulted (silver {c.consulted[1]}), "
        f"{c.numbers} numbers, {'ok' if c.ok else 'DIFFERS'}"
    ]
    lines += [f"  known: {k.day} {k.ball_type} {' '.join(k.numbers)} ({k.why})" for k in c.known]
    for ball, diffs in c.differences.items():
        lines += [f"  {ball} {n}: site {s}, silver {e}" for n, (s, e) in diffs.items()]
    return lines


def last_draws(silver_root: Path) -> dict[str, date]:
    last: dict[str, date] = {}
    for row in core_silver.read(silver_root, core_silver.DRAWS, ["game", "draw_date"]):
        last[row["game"]] = max(last.get(row["game"], row["draw_date"]), row["draw_date"])
    return last


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m sorteos.uy.estadisticas",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--root", type=Path, default=backfill.DEFAULT_ROOT)
    p.add_argument("--silver", type=Path, default=build_silver.DEFAULT_SILVER)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    from loteria.common.logging_setup import configure_logging

    configure_logging("loteria-uy-estadisticas")
    asked = queries(last_draws(args.silver))
    if not asked:
        print("silver is empty: nothing to ask", file=sys.stderr)
        return 1
    bronze = BronzeStore(args.root, COUNTRY)
    fetch(privacy.polite_client(), bronze, asked, backfill.today_in_uruguay())
    fetched, compared = compare_latest(bronze, args.silver)
    for c in compared:
        print("\n".join(describe(c)), file=sys.stderr)
    return 0 if all(c.ok for c in compared) else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
