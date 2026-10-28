"""``ver_resultados``: every v1 game drawn on one day, from one page (DESIGN.md, D3, D5, P1, P6).

A pure function of the bronze bytes and the requested date: no network, no clock. One page
template covers 2006–2026 (DESIGN.md, «La estructura del HTML casi no cambió»), so there is a
single parser epoch.

**Blocks.** Each game block ends in its ``MostrarExtracto('<code>', dd, mm, yyyy)`` link, the
site's own routing table. A block is the smallest table around that link which also holds a
block header image. The "Sorteos para el día de hoy" box carries the fetch date, which equals
the requested date on the day of the draw; it has no header image and no extract link, so it
never becomes a block.

**Two kinds of failure.** A page that cannot be trusted as a whole raises ``PageError`` and
the day goes to quarantine: a block dated on another day, an unknown game code, a header with
no extract link (the 2019 AFAL strike), the same game twice, or no block at all. A block whose
own content does not have the expected shape becomes a ``BlockError`` and only that draw goes
to quarantine; the other games of the day still parse. Nothing is ever filled in with a
probable value.

**What it returns is what was published.** Numbers keep their zeros (``'043'``). Dirty data
(a repeated Tómbola number in 2006, a "Próximo" with a three-digit year) comes back as
published; the ``dq_flags`` are derived when silver is written (UY-025), not here. Coupon
numbers are only counted and never leave this module (D7).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from sorteos.core.dates import parse_dmy
from sorteos.core.money import AmountError, parse_amount
from sorteos.uy.sources import CONFIG, ORO, QN, QV, game_for_code

SOURCE = "resultados"
_PAGE = CONFIG.site.pages[SOURCE]

_EXTRACT = re.compile(r"MostrarExtracto\(\s*'(\d+)'\s*,\s*'(\d+)'\s*,\s*'(\d+)'\s*,\s*'(\d+)'\s*\)")
# Block header images. Lotería's logo is renamed every year (LOGO_LOTERIA_2026.png on pages
# from 2006), hence the prefix.
_HEADER = re.compile(
    r"cabezal_quinielas_(?:vespertina|nocturno)|logo_5deoro|logo_kini|LOGO_LOTERIA", re.I
)
# The image next to each Quiniela number is its position: the HTML interleaves 1, 11, 2, 12…
_POSITION = re.compile(r"numeros_tablas/l_(\d{2})\.gif$")

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

# The 5 de Oro labels, in page order, and the prize each one opens.
_PRIZE_LABELS = (
    ("Pozo de Oro: $", "oro"),
    ("Pozo de Plata: $", "plata"),
    ("Pozo Revancha: $", "revancha"),
)
# "Sin Aciertos" as typed by hand over 20 years: «Sin Acierto», «SIN ACIERTO», «SinAciertos»,
# «Sin Acirtos», «si aciertos»… All of them are "si", an optional "n", then "a" and letters.
_NO_WINNERS = re.compile(r"si\s*n?\s*a[a-z]+", re.I)
# "Vacante" (2014-05-11, Oro and Revancha): the pool was not won.
_VACANT = "vacante"
# A coupon: digits with dashes, sometimes a stray trailing "|". Only counted.
_COUPON = re.compile(r"\d[\d-]{6,}\d\|?")

WINNERS = "winners"
NO_WINNERS = "no_winners"
UNKNOWN = "unknown"


class PageError(ValueError):
    """The page cannot be trusted as a whole: the day goes to quarantine."""


class BlockError(ValueError):
    """One block does not have the expected shape: that draw goes to quarantine."""


@dataclass(frozen=True)
class Ball:
    ball_type: str
    position: int
    number: str  # with its zeros, as published


@dataclass(frozen=True)
class Prize:
    prize: str
    pool_amount: Decimal | None  # None when the page prints a bare "$"
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


@dataclass(frozen=True)
class FailedDraw:
    game: str
    draw_date: date
    reason: str


@dataclass(frozen=True)
class ParsedPage:
    draw_date: date
    parser_version: int
    draws: tuple[ParsedDraw, ...]
    failed: tuple[FailedDraw, ...]
    skipped: tuple[str, ...]  # games on the page that v1 does not parse (Lotería, Kini)


def parser_version(day: date) -> int:
    for epoch in _PAGE.parser_epochs:
        if epoch.valid_from <= day and (epoch.valid_to is None or day <= epoch.valid_to):
            return epoch.version
    raise PageError(f"no parser epoch of {SOURCE} covers {day}")


def parse(content: bytes, day: date) -> ParsedPage:
    version = parser_version(day)
    soup = BeautifulSoup(content.decode("utf-8", errors="replace"), "html.parser")
    links = soup.find_all("a", onclick=_EXTRACT)
    headers = soup.find_all("img", src=_HEADER)
    if len(headers) != len(links):
        raise PageError(f"{len(headers)} block headers for {len(links)} extract links")
    if not links:
        raise PageError("no game blocks")

    draws: list[ParsedDraw] = []
    failed: list[FailedDraw] = []
    skipped: list[str] = []
    seen: set[str] = set()
    for link in links:
        code, dd, mm, yyyy = _EXTRACT.search(link["onclick"]).groups()
        game = game_for_code(int(code))
        if game.startswith("unknown_"):
            raise PageError(f"unknown game code {code}")
        if date(int(yyyy), int(mm), int(dd)) != day:
            raise PageError(f"code {code} dated {yyyy}-{mm}-{dd}")
        if game in seen:
            raise PageError(f"{game} appears twice")
        seen.add(game)
        if game not in CONFIG.games:
            skipped.append(game)
            continue
        block = _block(link)
        try:
            draws.append(_parse_block(game, block, day))
        except (BlockError, AmountError) as exc:
            failed.append(FailedDraw(game, day, str(exc)))
    return ParsedPage(day, version, tuple(draws), tuple(failed), tuple(skipped))


def _block(link: Tag) -> Tag:
    table = link.find_parent("table")
    while table is not None and table.find("img", src=_HEADER) is None:
        table = table.find_parent("table")
    if table is None or len(table.find_all("a", onclick=_EXTRACT)) != 1:
        raise PageError(f"no block of its own around {link['onclick']}")
    return table


def _tokens(block: Tag) -> list[tuple[str, int | None]]:
    """The block's texts in page order, each with the Quiniela position image before it."""
    out: list[tuple[str, int | None]] = []
    position = None
    for node in block.descendants:
        if isinstance(node, Tag) and node.name == "img":
            match = _POSITION.search(node.get("src", ""))
            if match:
                position = int(match.group(1))
        elif isinstance(node, NavigableString) and not isinstance(node, Comment):
            text = " ".join(node.split())
            if text:
                out.append((text, position))
                position = None
    return out


def _parse_block(game: str, block: Tag, day: date) -> ParsedDraw:
    tokens = _tokens(block)
    texts = [t for t, _ in tokens]
    if len(texts) < 2:
        raise BlockError("empty block")
    _check_date(texts[0], day)
    next_text, next_date = _next_draw(texts[-1], CONFIG.games[game].calendar.next_draw_label)
    body = tokens[1:-1]
    if game in (QV, QN):
        numbers, prizes = _quiniela(game, body), ()
    elif game == ORO:
        numbers, prizes = _cinco_de_oro(body)
    else:  # pragma: no cover — sources.py refuses a games/*.yaml the code does not know
        raise BlockError(f"no block parser for {game}")
    return ParsedDraw(game, day, next_text, next_date, numbers, prizes)


def _long_date(text: str) -> date | None:
    """``Miércoles 06 de Julio de 2016``, the form of every block header."""
    match = _LONG_DATE.fullmatch(text)
    month = _MONTHS.get(match.group(2).lower()) if match else None
    if not month:
        return None
    try:
        return date(int(match.group(3)), month, int(match.group(1)))
    except ValueError:
        return None


def _check_date(text: str, day: date) -> None:
    found = _long_date(text)
    if found is None:
        raise BlockError(f"no block date, found {text!r}")
    if found != day:
        raise BlockError(f"block dated {text!r}")


def _next_draw(text: str, label: str) -> tuple[str | None, date | None]:
    head, sep, value = text.partition(":")
    if not sep or " ".join(head.split()) != label:
        raise BlockError(f"expected {label!r} last, found {text!r}")
    value = value.strip()
    if not value:
        return None, None
    # Once (5 de Oro, 2006-08-23) it is written like a block header, which is unambiguous
    # and needs no digit corrected (owner, UY-022).
    return value, parse_dmy(value) or _long_date(value)


def _balls(ball_type: str, texts: list[str], game: str) -> tuple[Ball, ...]:
    spec = CONFIG.games[game].numbers[ball_type]
    if len(texts) != spec.count:
        raise BlockError(f"{len(texts)} {ball_type} numbers, expected {spec.count}")
    for text in texts:
        if not (text.isdigit() and len(text) == spec.digits):
            raise BlockError(f"{ball_type} number {text!r} is not {spec.digits} digits")
    return tuple(Ball(ball_type, i, text) for i, text in enumerate(texts, start=1))


def _quiniela(game: str, body: list[tuple[str, int | None]]) -> tuple[Ball, ...]:
    spec = CONFIG.games[game].numbers["quiniela"]
    placed = [(pos, text) for text, pos in body if pos is not None]
    rest = [text for text, pos in body if pos is None]
    if sorted(pos for pos, _ in placed) != list(range(1, spec.count + 1)):
        raise BlockError(f"quiniela positions {sorted(p for p, _ in placed)}")
    for _, text in placed:
        if not (text.isdigit() and len(text) == spec.digits):
            raise BlockError(f"quiniela number {text!r} is not {spec.digits} digits")
    quiniela = tuple(Ball("quiniela", pos, text) for pos, text in sorted(placed))
    if not rest:
        # Published without its Tómbola (once: the Vespertina of 2006-08-31). The Quiniela is
        # still a draw that can be read; the Tómbola simply has no rows (owner, UY-022).
        return quiniela
    return quiniela + _balls("tombola", rest, game)


def _cinco_de_oro(body: list[tuple[str, int | None]]) -> tuple[tuple[Ball, ...], tuple[Prize, ...]]:
    texts = [t for t, _ in body]
    at = []
    for label, _ in _PRIZE_LABELS:
        if texts.count(label) != 1:
            raise BlockError(f"{label!r} appears {texts.count(label)} times")
        at.append(texts.index(label))
    if at != sorted(at):
        raise BlockError("the pool labels are out of order")
    oro_i, plata_i, rev_i = at
    leading = texts[:oro_i]
    revancha_count = CONFIG.games[ORO].numbers["revancha"].count
    plata_cell = texts[plata_i + 1 : rev_i]
    numbers = (
        _balls("oro", leading[:-1], ORO)
        + _balls("extra", leading[-1:], ORO)
        + _balls("revancha", plata_cell[-revancha_count:], ORO)
    )
    prizes = (
        _prize("oro", texts[oro_i + 1 : plata_i]),
        _prize("plata", plata_cell[:-revancha_count]),
        _prize("revancha", texts[rev_i + 1 :]),
    )
    return numbers, prizes


def _prize(prize: str, cell: list[str]) -> Prize:
    amount = None
    if cell and re.fullmatch(r"[\d.,]+", cell[0]) and re.search(r"[.,]", cell[0]):
        amount = parse_amount(cell[0], _PAGE.money_style)
        cell = cell[1:]
    if not cell:
        return Prize(prize, amount, UNKNOWN, None)
    if len(cell) == 1 and (_NO_WINNERS.fullmatch(cell[0]) or cell[0].lower() == _VACANT):
        return Prize(prize, amount, NO_WINNERS, 0)
    if all(_COUPON.fullmatch(text) for text in cell):
        return Prize(prize, amount, WINNERS, len(cell))
    raise BlockError(f"{prize}: winners cell not understood ({len(cell)} texts)")
