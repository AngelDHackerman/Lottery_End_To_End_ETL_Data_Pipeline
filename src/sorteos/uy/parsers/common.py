"""What the three Uruguayan parsers share: the row shapes and the readings of hand-typed text.

Every parser returns the same ``ParsedDraw``, so ``cross_check.compare`` can set two sources of
one draw side by side. The helpers here read what the DNLQ typed by hand for 20 years: the
winners cell, the "Próximo" date and the shape of the numbers. None of them guesses: what does
not fit raises ``BlockError`` and the draw goes to quarantine (DESIGN.md, D5).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from bs4 import Comment, NavigableString, Tag

from sorteos.core.config import Epoch
from sorteos.core.dates import parse_dmy
from sorteos.uy.sources import CONFIG

WINNERS = "winners"
NO_WINNERS = "no_winners"
UNKNOWN = "unknown"

_MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "setiembre": 9,
    "septiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}
_LONG_DATE = re.compile(
    r"(?:Lunes|Martes|Miércoles|Jueves|Viernes|Sábado|Domingo) (\d{1,2}) de (\w+) de (\d{4})"
)
# "Sin Aciertos" as typed by hand over 20 years: «Sin Acierto», «SIN ACIERTO», «SinAciertos»,
# «Sin Acirtos», «si aciertos»… All of them are "si", an optional "n", then "a" and letters.
_NO_WINNERS = re.compile(r"si\s*n?\s*a[a-z]+", re.I)
# "Vacante" (2014-05-11, Oro and Revancha): the pool was not won.
_VACANT = "vacante"
# A coupon: digits with dashes, sometimes a stray trailing "|". Only counted.
_COUPON = re.compile(r"\d[\d-]{6,}\d\|?")


class BlockError(ValueError):
    """One draw does not have the expected shape: that draw goes to quarantine."""


@dataclass(frozen=True)
class Ball:
    ball_type: str
    position: int
    number: str  # with its zeros, as published


@dataclass(frozen=True)
class Prize:
    prize: str
    pool_amount: Decimal | None  # None when the source prints it empty
    winners_status: str  # winners | no_winners | unknown
    winning_coupons: int | None  # 0 with no_winners, None with unknown


@dataclass(frozen=True)
class ParsedDraw:
    game: str
    draw_date: date
    next_draw_text: str | None
    next_draw_date: date | None
    numbers: tuple[Ball, ...]
    prizes: tuple[Prize, ...] = ()
    # Only the Quiniela extract publishes them (P2): Montevideo wall-clock time, no zone.
    started_local: datetime | None = None
    first_ball_local: datetime | None = None
    ended_local: datetime | None = None


def epoch_version(epochs: tuple[Epoch, ...], day: date) -> int | None:
    """The parser epoch of a source that covers ``day``, from its YAML (D5)."""
    for epoch in epochs:
        if epoch.valid_from <= day and (epoch.valid_to is None or day <= epoch.valid_to):
            return epoch.version
    return None


def tokens(root: Tag, position: re.Pattern) -> list[tuple[str, int | None]]:
    """The texts under ``root`` in page order, each with the position image just before it."""
    out: list[tuple[str, int | None]] = []
    pending = None
    for node in root.descendants:
        if isinstance(node, Tag) and node.name == "img":
            match = position.search(node.get("src", ""))
            if match:
                pending = int(match.group(1))
        elif isinstance(node, NavigableString) and not isinstance(node, Comment):
            text = " ".join(node.split())
            if text:
                out.append((text, pending))
                pending = None
    return out


def long_date(text: str) -> date | None:
    """``Miércoles 06 de Julio de 2016``, the form of every ver_resultados block header."""
    match = _LONG_DATE.fullmatch(text)
    month = _MONTHS.get(match.group(2).lower()) if match else None
    if not month:
        return None
    try:
        return date(int(match.group(3)), month, int(match.group(1)))
    except ValueError:
        return None


def next_draw(text: str, label: str) -> tuple[str | None, date | None]:
    head, sep, value = text.partition(":")
    if not sep or " ".join(head.split()) != label:
        raise BlockError(f"expected {label!r}, found {text!r}")
    value = value.strip()
    if not value:
        return None, None
    # Once (5 de Oro, 2006-08-23) it is written like a block header, which is unambiguous
    # and needs no digit corrected (owner, UY-022).
    return value, parse_dmy(value) or long_date(value)


def balls(ball_type: str, texts: list[str], game: str) -> tuple[Ball, ...]:
    spec = CONFIG.games[game].numbers[ball_type]
    if len(texts) != spec.count:
        raise BlockError(f"{len(texts)} {ball_type} numbers, expected {spec.count}")
    for text in texts:
        if not (text.isdigit() and len(text) == spec.digits):
            raise BlockError(f"{ball_type} number {text!r} is not {spec.digits} digits")
    return tuple(Ball(ball_type, i, text) for i, text in enumerate(texts, start=1))


def quiniela(game: str, placed: list[tuple[int, str]], tombola: list[str]) -> tuple[Ball, ...]:
    """The 20 Quiniela numbers by the position their image gives, then the Tómbola."""
    spec = CONFIG.games[game].numbers["quiniela"]
    if sorted(pos for pos, _ in placed) != list(range(1, spec.count + 1)):
        raise BlockError(f"quiniela positions {sorted(p for p, _ in placed)}")
    for _, text in placed:
        if not (text.isdigit() and len(text) == spec.digits):
            raise BlockError(f"quiniela number {text!r} is not {spec.digits} digits")
    numbers = tuple(Ball("quiniela", pos, text) for pos, text in sorted(placed))
    if not tombola:
        # Published without its Tómbola (once: the Vespertina of 2006-08-31). The Quiniela is
        # still a draw that can be read; the Tómbola simply has no rows (owner, UY-022).
        return numbers
    return numbers + balls("tombola", tombola, game)


def winners(prize: str, cell: list[str]) -> tuple[str, int | None]:
    """The winners cell of one prize: (status, how many coupons). Coupons are only counted."""
    if not cell:
        return UNKNOWN, None
    if len(cell) == 1 and (_NO_WINNERS.fullmatch(cell[0]) or cell[0].lower() == _VACANT):
        return NO_WINNERS, 0
    if all(_COUPON.fullmatch(text) for text in cell):
        return WINNERS, len(cell)
    raise BlockError(f"{prize}: winners cell not understood ({len(cell)} texts)")
