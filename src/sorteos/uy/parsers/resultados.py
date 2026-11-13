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
numbers are only counted and never leave the parser (D7). The row shapes and the readings of
hand-typed text are shared with the extract parsers (``common.py``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from bs4 import BeautifulSoup, Tag

from sorteos.core.money import AmountError, parse_amount
from sorteos.uy.parsers.common import (
    NO_WINNERS,
    UNKNOWN,
    WINNERS,
    Ball,
    BlockError,
    ParsedDraw,
    Prize,
    balls,
    epoch_version,
    long_date,
    next_draw,
    quiniela,
    tokens,
    winners,
)
from sorteos.uy.sources import CONFIG, ORO, QN, QV, game_for_code

__all__ = ["NO_WINNERS", "UNKNOWN", "WINNERS", "Ball", "BlockError", "ParsedDraw", "Prize"]

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

# The 5 de Oro labels, in page order, and the prize each one opens.
_PRIZE_LABELS = (
    ("Pozo de Oro: $", "oro"),
    ("Pozo de Plata: $", "plata"),
    ("Pozo Revancha: $", "revancha"),
)


class PageError(ValueError):
    """The page cannot be trusted as a whole: the day goes to quarantine."""


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
    version = epoch_version(_PAGE.parser_epochs, day)
    if version is None:
        raise PageError(f"no parser epoch of {SOURCE} covers {day}")
    return version


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


def _parse_block(game: str, block: Tag, day: date) -> ParsedDraw:
    found = tokens(block, _POSITION)
    texts = [t for t, _ in found]
    if len(texts) < 2:
        raise BlockError("empty block")
    _check_date(texts[0], day)
    next_text, next_date = next_draw(texts[-1], CONFIG.games[game].calendar.next_draw_label)
    body = found[1:-1]
    if game in (QV, QN):
        placed = [(pos, text) for text, pos in body if pos is not None]
        rest = [text for text, pos in body if pos is None]
        numbers, prizes = quiniela(game, placed, rest), ()
    elif game == ORO:
        numbers, prizes = _cinco_de_oro(body)
    else:  # pragma: no cover — sources.py refuses a games/*.yaml the code does not know
        raise BlockError(f"no block parser for {game}")
    return ParsedDraw(game, day, next_text, next_date, numbers, prizes)


def _check_date(text: str, day: date) -> None:
    found = long_date(text)
    if found is None:
        raise BlockError(f"no block date, found {text!r}")
    if found != day:
        raise BlockError(f"block dated {text!r}")


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
        balls("oro", leading[:-1], ORO)
        + balls("extra", leading[-1:], ORO)
        + balls("revancha", plata_cell[-revancha_count:], ORO)
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
    return Prize(prize, amount, *winners(prize, cell))
