"""``ver_estadisticas.php``: how many times each number came out in a range (UY-030.2).

A pure function, bytes in, counts out. The page answers a POST of its own form (FINDINGS,
Q10) with "Cantidad de sorteos consultados: N" and one grid per kind of ball:

- the 5 de Oro (``xjue=4``): a "5 de Oro" grid, then a "Revancha" grid, 2-digit numbers;
- the Quiniela (``xjue=2``, the Vespertina only, UY-030.2): one grid of 3-digit numbers under
  the headers 0 to 9 (the hundreds);
- the Tómbola (``xjue=3``): one grid of 2-digit numbers.

Each grid is pairs of cells, number then count, read in page order. Only numbers that came
out are listed. The cells are read as a small state machine: a header (``Número``, ``Veces``
or a hundreds digit) is skipped, a title opens a new grid, and the first cell that is none
of these ends the results. Anything that breaks the shape raises ``StatsError``: these
counts check silver, so a half-read page must never pass for a small one.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from bs4 import BeautifulSoup

#: The grid titles of the 5 de Oro page, as the ball types of silver.
TITLES = {"5 de Oro": "oro", "Revancha": "revancha"}
UNTITLED = ""  # the one grid of the Quiniela and Tómbola pages

_CONSULTED = re.compile(r"Cantidad de sorteos consultados:\s*(\d+)")
_HEADERS = frozenset({"Número", "Veces", *map(str, range(10))})
_NUMBER = re.compile(r"\d{2,3}")
_COUNT = re.compile(r"\d+")


class StatsError(ValueError):
    """The page does not have the shape of a ``ver_estadisticas`` answer."""


@dataclass(frozen=True)
class Stats:
    consulted: int  # "Cantidad de sorteos consultados"
    grids: dict[str, Counter]  # grid title (a TITLES key, or UNTITLED) -> number -> times


def parse(content: bytes) -> Stats:
    soup = BeautifulSoup(content, "html.parser")
    cells = [_text(td) for td in soup.find_all("td") if td.find("td") is None]
    start = next((i for i, c in enumerate(cells) if _CONSULTED.search(c)), None)
    if start is None:
        raise StatsError("no 'Cantidad de sorteos consultados'")
    consulted = int(_CONSULTED.search(cells[start]).group(1))

    grids: dict[str, Counter] = {}
    grid: Counter | None = None
    number: str | None = None
    for cell in cells[start + 1 :]:
        if number is not None:  # a count must follow a number
            if not _COUNT.fullmatch(cell):
                raise StatsError(f"number {number} without a count: {cell!r}")
            grid[number] = int(cell)
            number = None
        elif not cell or cell in _HEADERS:
            continue
        elif cell in TITLES:
            grid = grids.setdefault(cell, Counter())
        elif _NUMBER.fullmatch(cell):
            if grid is None:
                grid = grids.setdefault(UNTITLED, Counter())
            if cell in grid:
                raise StatsError(f"{cell} listed twice")
            number = cell
        else:
            break  # past the results: the page footer
    if number is not None:
        raise StatsError(f"number {number} without a count at the end")
    for title, counts in grids.items():
        widths = {len(n) for n in counts}
        if len(widths) > 1:
            raise StatsError(f"grid {title or 'untitled'!r} mixes {sorted(widths)}-digit numbers")
    if consulted and not any(grids.values()):
        raise StatsError(f"{consulted} draws consulted and no number listed")
    return Stats(consulted, grids)


def _text(td) -> str:
    return " ".join(td.get_text(" ").replace("\xa0", " ").split())
