"""The Quiniela extract (``extracto_Q{V,N}_S.php``): the timing of a draw and a second reading.

One page per shift and date, one template from 2006 to 2026 (DESIGN.md, «La estructura del HTML
casi no cambió»). ``ver_resultados`` is the primary source of the numbers; this page adds the
three times of the draw (P2) and is the cross-check of the numbers (``cross_check.compare``).

- Each Quiniela number follows its position image (``p_N.gif``), as in ver_resultados.
- "Inicio", "Primero" and "Fin" each carry ``HH:MM hrs.``: Montevideo wall-clock time, kept
  without a zone (the zone is a column of silver). An empty ``hrs.`` is null (once, the
  Vespertina of 2006-08-31). A time is never reordered or corrected: the Nocturna of 2009-08-01
  ends at 15:24 after starting at 21:00, and that is what comes back (the flag is UY-025's).
- What follows "Próximo Sorteo" (the officials who sign the extract) is never read.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from bs4 import BeautifulSoup

from sorteos.uy.parsers.common import (
    BlockError,
    ParsedDraw,
    epoch_version,
    next_draw,
    quiniela,
    tokens,
)
from sorteos.uy.sources import CONFIG, QN, QV

_POSITION = re.compile(r"/p_(\d{1,2})\.gif$")
_DATE = re.compile(
    r"(?:Lunes|Martes|Miércoles|Jueves|Viernes|Sábado|Domingo) (\d{2})/(\d{2})/(\d{4})"
)
_TIME = re.compile(r"(?:(\d{1,2}):(\d{2}) )?hrs\.")
TIMING_LABELS = ("Inicio", "Primero", "Fin")
NEXT_DRAW_LABEL = "Próximo Sorteo"


def source_name(game: str) -> str:
    return f"extracto_{game}"


def parser_version(game: str, day: date) -> int:
    (spec,) = (s for s in CONFIG.games[game].sources if s.name == source_name(game))
    version = epoch_version(spec.parser_epochs, day)
    if version is None:
        raise BlockError(f"no parser epoch of {spec.name} covers {day}")
    return version


def check_date(texts: list[str], day: date) -> int:
    """Index of the header date, which must be ``day``. Shared with the 5 de Oro extract."""
    for i, text in enumerate(texts):
        match = _DATE.fullmatch(text)
        if match:
            dd, mm, yyyy = (int(g) for g in match.groups())
            if (yyyy, mm, dd) != (day.year, day.month, day.day):
                raise BlockError(f"extract dated {text!r}")
            return i
    raise BlockError("no header date")


def parse(content: bytes, day: date, game: str) -> ParsedDraw:
    if game not in (QV, QN):
        raise ValueError(f"not a Quiniela: {game}")
    parser_version(game, day)
    soup = BeautifulSoup(content.decode("utf-8", errors="replace"), "html.parser")
    found = tokens(soup, _POSITION)
    texts = [t for t, _ in found]
    start = check_date(texts, day)
    nexts = [i for i, t in enumerate(texts) if i > start and t.startswith(NEXT_DRAW_LABEL)]
    if len(nexts) != 1:
        raise BlockError(f"{len(nexts)} {NEXT_DRAW_LABEL!r} lines")
    body = found[start + 1 : nexts[0]]
    placed = [(pos, text) for text, pos in body if pos is not None]
    rest = [text for text, pos in body if pos is None]
    if tuple(rest[0:6:2]) != TIMING_LABELS:
        raise BlockError(f"expected {TIMING_LABELS} after the numbers, found {rest[0:6:2]}")
    started, first_ball, ended = (_time(rest[i], day) for i in (1, 3, 5))
    next_text, next_date = next_draw(texts[nexts[0]], NEXT_DRAW_LABEL)
    return ParsedDraw(
        game,
        day,
        next_text,
        next_date,
        quiniela(game, placed, rest[6:]),
        started_local=started,
        first_ball_local=first_ball,
        ended_local=ended,
    )


def _time(text: str, day: date) -> datetime | None:
    match = _TIME.fullmatch(text)
    if not match:
        raise BlockError(f"{text!r} is not a time")
    if match.group(1) is None:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    if hour > 23 or minute > 59:
        raise BlockError(f"{text!r} is not a time of day")
    return datetime(day.year, day.month, day.day, hour, minute)
