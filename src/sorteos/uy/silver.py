"""Bronze to silver rows for Uruguay: one year at a time, read from the manifest (UY-025.2).

``ver_resultados`` is the primary source (D6): every draw it shows is a row of ``draws``, with
its numbers and prizes as published there. The game's PHP extract is read beside it, for two
things: the Quiniela's timing (P2) and the control. ``compare()`` (UY-023) decides
``cross_source_check``: a different amount is ``amount_sources_differ`` on that prize and
anything else is ``mismatch``; silver keeps ver_resultados' values either way.

What goes to quarantine, never half into silver:

- a ver_resultados page that does not parse (``PageError``): the whole day, ``game`` null;
- a block of it that does not parse (``FailedDraw``), or whose numbers break the shape of the
  YAML (``core/shapes.py``: range, repeats, ``not_in``, order): that draw;
- an extract the manifest has as ``draw`` that does not parse: that draw too (owner, UY-025
  2a). An extract that is not there (no ``draw`` in the manifest) is ``not_checked``.

Every flag of one draw is set here (D21). The two that need the neighbours, the draw number
inferred or out of sequence, come with the pozos PDF in UY-025.3: until then ``draw_number``
is null. The lineage points to the ver_resultados page and ``parser_version`` lists every
source that gave something to the row, the primary first (owner, UY-025 3a).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from sorteos.core import manifest as mf
from sorteos.core import shapes, silver
from sorteos.core.bronze import BronzeStore
from sorteos.core.money import AmountError
from sorteos.uy import dq_flags as dq
from sorteos.uy.parsers import cross_check, extracto_5_de_oro, extracto_quiniela, resultados
from sorteos.uy.parsers.common import BlockError, ParsedDraw
from sorteos.uy.sources import CONFIG, COUNTRY, ORO

MATCH = "match"
MISMATCH = "mismatch"
NOT_CHECKED = "not_checked"
# P10: an announcement is believed up to 14 days after the draw that made it.
ANNOUNCEMENT_CAP = timedelta(days=14)
REFERENCE = Path(__file__).parent / "reference"
# The ranges of the YAML's range_rule, read from game_rules when the module loads (PR-049).
RANGES = shapes.load_ranges(
    REFERENCE / "game_rules.csv",
    {
        (g.game, s.range_rule)
        for g in CONFIG.games.values()
        for s in g.numbers.values()
        if s.range_rule
    },
)


class BronzeMismatch(RuntimeError):
    """A bronze file is not what the manifest says it fetched: the store, not the data."""


@dataclass(frozen=True)
class Run:
    ingested_at: datetime  # silver.utc_now(), once per run
    run_id: str | None = None


@dataclass
class YearRows:
    draws: list[dict] = field(default_factory=list)
    draw_numbers: list[dict] = field(default_factory=list)
    prizes: list[dict] = field(default_factory=list)
    quarantine: list[dict] = field(default_factory=list)


@dataclass(frozen=True)
class _Page:
    source: str
    key: str
    sha256: str
    content: bytes


def extract_source(game: str) -> str:
    return extracto_5_de_oro.SOURCE if game == ORO else extracto_quiniela.source_name(game)


def build_year(year: int, manifest: mf.Manifest, bronze: BronzeStore, run: Run) -> YearRows:
    """Every row of ``year``, from the pages the manifest has as ``draw``. No requests."""
    rows = YearRows()
    day = date(year, 1, 1)
    while day.year == year:
        page = _page(manifest, bronze, resultados.SOURCE, day)
        if page:
            _day(page, day, manifest, bronze, run, rows)
        day += timedelta(days=1)
    return rows


def write_year(root: Path, year: int, rows: YearRows) -> list[Path]:
    """Rewrite ``year`` in the four tables (D17); a table with no rows loses that year."""
    written = []
    for table, members in (
        (silver.DRAWS, rows.draws),
        (silver.DRAW_NUMBERS, rows.draw_numbers),
        (silver.PRIZES, rows.prizes),
        (silver.QUARANTINE, rows.quarantine),
    ):
        written += silver.write(root, table, members, country=COUNTRY, year=year, flags=dq.CATALOG)
    return written


def write_reference(root: Path, run: Run) -> list[Path]:
    """``game_rules`` and ``calendar_events``, as their CSVs say."""
    written = []
    for table in (silver.GAME_RULES, silver.CALENDAR_EVENTS):
        path = REFERENCE / f"{table.name}.csv"
        rows = silver.read_reference(
            path,
            table,
            country=COUNTRY,
            operator=CONFIG.site.operator,
            ingested_at=run.ingested_at,
            run_id=run.run_id,
            source_key=f"src/sorteos/uy/reference/{path.name}",
        )
        written += silver.write(root, table, rows, country=COUNTRY)
    return written


def _page(manifest: mf.Manifest, bronze: BronzeStore, source: str, day: date) -> _Page | None:
    if manifest.effective_state(source, day) != mf.DRAW:
        return None
    record = manifest.get(source, day)
    content = bronze.read(record["bronze_key"])
    if hashlib.sha256(content).hexdigest() != record["content_sha256"]:
        raise BronzeMismatch(f"{record['bronze_key']} is not the page the manifest fetched")
    return _Page(source, record["bronze_key"], record["content_sha256"], content)


def _day(
    page: _Page, day: date, manifest: mf.Manifest, bronze: BronzeStore, run: Run, rows: YearRows
) -> None:
    versions: dict[str, int] = {}
    try:
        versions[page.source] = resultados.parser_version(day)
        parsed = resultados.parse(page.content, day)
    except resultados.PageError as exc:
        rows.quarantine.append(_quarantined(page, day, None, str(exc), versions, run))
        return
    for failed in parsed.failed:
        rows.quarantine.append(_quarantined(page, day, failed.game, failed.reason, versions, run))
    for draw in parsed.draws:
        wrong = _shape_problems(draw)
        if wrong:
            rows.quarantine.append(
                _quarantined(page, day, draw.game, "; ".join(wrong), versions, run)
            )
            continue
        draw_versions = dict(versions)
        other = None
        extract = _page(manifest, bronze, extract_source(draw.game), day)
        if extract:
            try:
                if draw.game == ORO:
                    draw_versions[extract.source] = extracto_5_de_oro.parser_version(day)
                    other = extracto_5_de_oro.parse(extract.content, day)
                else:
                    draw_versions[extract.source] = extracto_quiniela.parser_version(draw.game, day)
                    other = extracto_quiniela.parse(extract.content, day, draw.game)
            except (BlockError, AmountError) as exc:
                rows.quarantine.append(
                    _quarantined(extract, day, draw.game, str(exc), draw_versions, run)
                )
                continue
        _rows(draw, other, page, draw_versions, run, rows)


def _shape_problems(draw: ParsedDraw) -> list[str]:
    numbers = CONFIG.games[draw.game].numbers
    published = {
        ball_type: [b.number for b in draw.numbers if b.ball_type == ball_type]
        for ball_type in numbers
    }
    # The Tómbola's repeats are a flag of the catalog (31, all from 2006), not a quarantine.
    flagged = {ball_type for ball_type, spec in numbers.items() if spec.replacements_from}
    return shapes.problems(draw.game, draw.draw_date, numbers, published, RANGES, flagged)


def _rows(
    draw: ParsedDraw,
    other: ParsedDraw | None,
    page: _Page,
    versions: dict[str, int],
    run: Run,
    rows: YearRows,
) -> None:
    lineage = {
        "ingested_at": run.ingested_at,
        "run_id": run.run_id,
        "source_key": page.key,
        "source_sha256": page.sha256,
        "parser_version": silver.parser_version(versions),
    }
    ref = {
        "country": COUNTRY,
        "operator": CONFIG.site.operator,
        "game": draw.game,
        "draw_date": draw.draw_date,
    }
    differences = cross_check.compare(draw, other) if other else ()
    amounts_differ = {
        d.field.split(":", 1)[1] for d in differences if d.field.startswith("pool_amount:")
    }
    if other is None:
        check = NOT_CHECKED
    elif len(amounts_differ) < len(differences):
        check = MISMATCH
    else:
        check = MATCH

    numbers = CONFIG.games[draw.game].numbers
    replacements, number_flags = _replacements(draw, numbers)
    timing = other if other and draw.game != ORO else None
    rows.draws.append(
        ref
        | {
            "draw_number": None,  # UY-025.3
            "next_draw_text": draw.next_draw_text,
            "next_draw_date": draw.next_draw_date,
            "started_local": timing.started_local if timing else None,
            "first_ball_local": timing.first_ball_local if timing else None,
            "ended_local": timing.ended_local if timing else None,
            "timezone": CONFIG.site.timezone,
            "cross_source_check": check,
            "dq_flags": _draw_flags(draw, timing) + number_flags,
        }
        | lineage
    )
    for ball in draw.numbers:
        rows.draw_numbers.append(
            ref
            | {
                "ball_type": ball.ball_type,
                "position": ball.position,
                "is_draw_order": numbers[ball.ball_type].order == "drawn",
                "number": ball.number,
                "is_replacement": replacements.get(ball.ball_type, {}).get(ball.position),
            }
            | lineage
        )
    pools = {p.prize: p.pool_amount for p in draw.prizes}
    for prize in draw.prizes:
        flags = []
        if prize.prize == "plata" and prize.pool_amount is not None:
            if prize.pool_amount == pools.get("oro"):
                flags.append(dq.POZO_PLATA_EQUALS_ORO)
        if prize.prize in amounts_differ:
            flags.append(dq.AMOUNT_SOURCES_DIFFER)
        rows.prizes.append(
            ref
            | {
                "prize": prize.prize,
                "pool_amount": prize.pool_amount,
                "currency": CONFIG.site.currency,
                "winners_status": prize.winners_status,
                "winning_coupons": prize.winning_coupons,
                "dq_flags": flags,
            }
            | lineage
        )


def _draw_flags(draw: ParsedDraw, timing: ParsedDraw | None) -> list[str]:
    flags = []
    if draw.next_draw_text is not None and draw.next_draw_date is None:
        flags.append(dq.NEXT_DRAW_UNPARSED)
    announced = draw.next_draw_date
    if announced and not draw.draw_date < announced <= draw.draw_date + ANNOUNCEMENT_CAP:
        flags.append(dq.NEXT_DRAW_IMPLAUSIBLE)
    if timing:
        published = (timing.started_local, timing.first_ball_local, timing.ended_local)
        times = [t for t in published if t]
        if times != sorted(times):
            flags.append(dq.TIMING_OUT_OF_ORDER)
    return flags


def _replacements(draw: ParsedDraw, numbers: dict) -> tuple[dict[str, dict[int, bool]], list[str]]:
    """P7: a ball of a type with ``replacements_from`` is a replacement when it is not one of
    the endings of that other type's numbers.

    It holds when the endings are all there and the replacements fill the rest exactly; when
    not (``tombola_not_from_quiniela``, all from 2006), ``is_replacement`` stays null in the
    draw. A repeated number is flagged on its own as well.
    """
    out: dict[str, dict[int, bool]] = {}
    flags: list[str] = []
    for ball_type, spec in numbers.items():
        balls = [b for b in draw.numbers if b.ball_type == ball_type]
        if not spec.replacements_from or not balls:  # 2006-08-31: a Quiniela without Tómbola
            continue
        published = [b.number for b in balls]
        source = [b.number for b in draw.numbers if b.ball_type == spec.replacements_from]
        endings = {n[-spec.digits :] for n in source}
        repeated = len(set(published)) != len(published)
        if repeated:
            flags.append(dq.TOMBOLA_REPEATED_NUMBER)
        new = set(published) - endings
        if repeated or not endings <= set(published) or len(new) != len(source) - len(endings):
            flags.append(dq.TOMBOLA_NOT_FROM_QUINIELA)
            continue
        out[ball_type] = {b.position: b.number not in endings for b in balls}
    return out, flags


def _quarantined(
    page: _Page, day: date, game: str | None, reason: str, versions: dict[str, int], run: Run
) -> dict:
    return {
        "country": COUNTRY,
        "operator": CONFIG.site.operator,
        "source": page.source,
        "draw_date": day,
        "game": game,
        "reason": reason,
        "ingested_at": run.ingested_at,
        "run_id": run.run_id,
        "source_key": page.key,
        "source_sha256": page.sha256,
        "parser_version": silver.parser_version(versions) if versions else None,
    }
