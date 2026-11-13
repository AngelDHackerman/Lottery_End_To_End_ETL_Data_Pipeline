"""The 5 de Oro extract (``extracto_5_de_oro.php``): a second reading of the draw.

Nothing here is silver's own: ``ver_resultados`` is the primary source, and this page is its
cross-check (DESIGN.md, «Parsers y montos»), through ``cross_check.compare``.

- The 11 numbers are the cells styled ``Estilo_aproximaciones_nro``: 5 de Oro, the extra
  ball (labelled "Bolilla Extra:" right after it) and 5 de Revancha.
- The three pools are in the Uruguayan style (``2.472.229,46``, D6); ``0,00`` is the empty
  template's marker and reads as null, never 0.
- The winners cells are the last row of each table holding "Cupón Nro:" labels, one cell per
  prize in column order: Oro and Plata side by side, then Revancha. Reading them by cell, not
  by text order, is what keeps an empty cell empty instead of shifting the next one into it.
- What follows "Próximo Sorteo" (the officials who sign the extract) is never read.
"""

from __future__ import annotations

import re
from datetime import date

from bs4 import BeautifulSoup

from sorteos.core.money import parse_amount
from sorteos.uy.parsers.common import (
    BlockError,
    ParsedDraw,
    Prize,
    balls,
    epoch_version,
    next_draw,
    tokens,
    winners,
)
from sorteos.uy.parsers.extracto_quiniela import NEXT_DRAW_LABEL, check_date
from sorteos.uy.sources import CONFIG, ORO

SOURCE = "extracto_5_de_oro"
(_SPEC,) = (s for s in CONFIG.games[ORO].sources if s.name == SOURCE)
_NUMBER_CLASS = "Estilo_aproximaciones_nro"
_EXTRA_LABEL = "Bolilla Extra:"
_AMOUNT = re.compile(r"[\d.]+,\d{2}")
_NOTHING = re.compile(r"(?!)")  # this page has no position images
# Winners tables in page order, and the prizes of their cells in column order.
_CELLS = (("oro", "plata"), ("revancha",))


def parser_version(day: date) -> int:
    version = epoch_version(_SPEC.parser_epochs, day)
    if version is None:
        raise BlockError(f"no parser epoch of {SOURCE} covers {day}")
    return version


def parse(content: bytes, day: date) -> ParsedDraw:
    parser_version(day)
    soup = BeautifulSoup(content.decode("utf-8", errors="replace"), "html.parser")
    texts = [t for t, _ in tokens(soup, _NOTHING)]
    start = check_date(texts, day)

    # The class is on each number's cell and also on the row holding five of them.
    found = [" ".join(el.get_text().split()) for el in soup.find_all("td", class_=_NUMBER_CLASS)]
    if len(found) != 11:
        raise BlockError(f"{len(found)} numbers, expected 5 + 1 + 5")
    extra_at = texts.index(found[5], start) if found[5] in texts[start:] else -1
    if texts[extra_at + 1 : extra_at + 2] != [_EXTRA_LABEL]:
        raise BlockError(f"the sixth number is not followed by {_EXTRA_LABEL!r}")
    numbers = balls("oro", found[:5], ORO) + balls("extra", found[5:6], ORO)
    numbers += balls("revancha", found[6:], ORO)

    amounts = [t for t in texts[start:] if _AMOUNT.fullmatch(t)]
    cells = _winner_cells(soup)
    if len(amounts) != 3:
        raise BlockError(f"{len(amounts)} pool amounts, expected 3")
    prizes = tuple(
        Prize(prize, parse_amount(amount, _SPEC.money_style), *winners(prize, cell))
        for (prize, cell), amount in zip(cells, amounts, strict=True)
    )

    nexts = [t for t in texts[start:] if t.startswith(NEXT_DRAW_LABEL)]
    if len(nexts) != 1:
        raise BlockError(f"{len(nexts)} {NEXT_DRAW_LABEL!r} lines")
    next_text, next_date = next_draw(nexts[0], NEXT_DRAW_LABEL)
    return ParsedDraw(ORO, day, next_text, next_date, numbers, prizes)


def _winner_cells(soup: BeautifulSoup) -> list[tuple[str, list[str]]]:
    tables = []
    for label in soup.find_all(string=lambda s: s and "Cupón Nro:" in s):
        table = label.find_parent("table")
        if table not in tables:
            tables.append(table)
    if len(tables) != len(_CELLS):
        raise BlockError(f"{len(tables)} winners tables, expected {len(_CELLS)}")
    out = []
    for table, prizes in zip(tables, _CELLS, strict=True):
        cells = table.find_all("tr", recursive=False)[-1].find_all("td", recursive=False)
        if len(cells) != len(prizes):
            raise BlockError(f"{len(cells)} winners cells for {prizes}")
        out += [
            (prize, [" ".join(s.split()) for s in cell.stripped_strings])
            for prize, cell in zip(prizes, cells, strict=True)
        ]
    return out
