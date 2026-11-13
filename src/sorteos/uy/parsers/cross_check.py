"""Two readings of one draw, side by side (DESIGN.md, ``cross_source_check`` and D6).

``ver_resultados`` is the primary source; the PHP extract of the same game and date is the
control. Q1 found both agree on every value of 2,072 draws of the 5 de Oro, and DESIGN on every
number of 10,877 Quinielas, so a difference here is a parser bug or a source that changed, and
either way a person should look.

``compare`` only lists the differences, field by field. What they mean for silver is decided
when silver is written (UY-025): a pool amount that differs is ``amount_sources_differ`` on
that prize, anything else makes the draw's ``cross_source_check`` a ``mismatch``. The times
are not compared: only the extract has them.
"""

from __future__ import annotations

from dataclasses import dataclass

from sorteos.uy.parsers.common import ParsedDraw


@dataclass(frozen=True)
class Difference:
    field: str  # numbers:<ball_type> | next_draw | pool_amount:<prize> | winners:<prize>
    primary: object
    other: object


def compare(primary: ParsedDraw, other: ParsedDraw) -> tuple[Difference, ...]:
    if (primary.game, primary.draw_date) != (other.game, other.draw_date):
        raise ValueError(
            f"not the same draw: {primary.game} {primary.draw_date} "
            f"and {other.game} {other.draw_date}"
        )
    out: list[Difference] = []
    for ball_type in sorted({b.ball_type for b in (*primary.numbers, *other.numbers)}):
        mine = tuple((b.position, b.number) for b in primary.numbers if b.ball_type == ball_type)
        theirs = tuple((b.position, b.number) for b in other.numbers if b.ball_type == ball_type)
        if mine != theirs:
            out.append(Difference(f"numbers:{ball_type}", mine, theirs))

    mine_next = primary.next_draw_date or _plain(primary.next_draw_text)
    theirs_next = other.next_draw_date or _plain(other.next_draw_text)
    if mine_next != theirs_next:
        out.append(Difference("next_draw", primary.next_draw_text, other.next_draw_text))

    theirs_prizes = {p.prize: p for p in other.prizes}
    for prize in primary.prizes:
        twin = theirs_prizes.pop(prize.prize, None)
        if twin is None:
            out.append(Difference(f"winners:{prize.prize}", prize.winners_status, None))
            continue
        if prize.pool_amount != twin.pool_amount:
            out.append(
                Difference(f"pool_amount:{prize.prize}", prize.pool_amount, twin.pool_amount)
            )
        mine_w = (prize.winners_status, prize.winning_coupons)
        theirs_w = (twin.winners_status, twin.winning_coupons)
        if mine_w != theirs_w:
            out.append(Difference(f"winners:{prize.prize}", mine_w, theirs_w))
    for name, twin in theirs_prizes.items():
        out.append(Difference(f"winners:{name}", None, twin.winners_status))
    return tuple(out)


def _plain(text: str | None) -> str | None:
    return " ".join(text.split()) if text else None
