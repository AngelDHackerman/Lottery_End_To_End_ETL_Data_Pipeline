"""Decide what a raw page holds — a draw, nothing, or something unexpected.

This is NOT the silver parser: it extracts no numbers. It answers only what the manifest
needs to know (is there a draw for the requested date, and of which games) so the backfill
can decide what to keep in bronze and what to fetch next. Every rule below was observed on
2026-10-04 and is written down in docs/uruguay/FINDINGS.md.

The site never says "no draw" with a status code (the PHP pages answer 200 with an empty
template), so every rule here reads content:

- results page: the ``MostrarExtracto('<code>','dd','mm','yyyy')`` calls, one per game
  block. A code dated other than the requested day is a mismatch, never a draw. The block
  header images are checked against the codes as a second, independent signal.
- PHP extract: the header date ``dd/mm/yyyy``; the empty template prints ``//``.
- PDF: ``%PDF`` magic with HTTP 200; 404 means nothing was published.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from loteria_uy.http_client import blocked_pattern
from loteria_uy.sources import BASE_URL, KINI, ORO, QN, QV, game_for_code

CLASSIFIER_VERSION = "2026-10-04"

DRAW = "draw"
EMPTY = "empty"  # the caller turns this into no_draw / not_yet_published / missing
ERROR = "error"

_ONCLICK = re.compile(r"MostrarExtracto\(\s*'(\d+)'\s*,\s*'(\d+)'\s*,\s*'(\d+)'\s*,\s*'(\d+)'\s*\)")
_HEADER_DATE = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")
# A bare "//" where the date goes — but not the "//" of a URL printed in the page text.
_EMPTY_DATE = re.compile(r"(?<![\w:/])//(?![\w/])")

# Block header image -> game. Lotería's logo is renamed every year (LOGO_LOTERIA_2026.png
# on pages from 2006), so it is deliberately not a marker.
_MARKERS = {
    "cabezal_quinielas_vespertina": QV,
    "cabezal_quinielas_nocturno": QN,
    "logo_5deoro": ORO,
    "logo_kini": KINI,
}

POZOS_PATTERN = "RES_INFORMACION_DE_POZOS"


@dataclass(frozen=True)
class Classification:
    outcome: str  # DRAW | EMPTY | ERROR
    games: tuple[str, ...] = ()
    detail: str = ""
    warnings: tuple[str, ...] = ()
    extra: dict = field(default_factory=dict)


def _decode(content: bytes) -> str:
    # Every page observed declares charset=UTF-8 and is valid UTF-8; the "Pe?aloza" seen in
    # old extracts is a literal "?" stored at the source, not a decoding artefact here.
    return content.decode("utf-8", errors="replace")


def classify_resultados(content: bytes, day: date) -> Classification:
    html = _decode(content)
    games: list[str] = []
    for code, dd, mm, yyyy in _ONCLICK.findall(html):
        if date(int(yyyy), int(mm), int(dd)) != day:
            return Classification(ERROR, detail=f"code {code} dated {yyyy}-{mm}-{dd}")
        game = game_for_code(int(code))
        if game not in games:
            games.append(game)

    soup = BeautifulSoup(html, "html.parser")
    srcs = [img.get("src", "") for img in soup.find_all("img")]
    marked = {game for stem, game in _MARKERS.items() if any(stem in s for s in srcs)}
    warnings = []
    for game in sorted(marked.symmetric_difference(set(games) & set(_MARKERS.values()))):
        warnings.append(f"marker_mismatch:{game}")

    extra = {}
    pozos = pozos_href(soup)
    if pozos:
        extra["pozos_url"] = pozos

    if not games:
        if marked:
            return Classification(ERROR, detail="game blocks without extract codes")
        return Classification(EMPTY)
    return Classification(DRAW, games=tuple(games), warnings=tuple(warnings), extra=extra)


def pozos_href(soup: BeautifulSoup) -> str | None:
    """The 5 de Oro pozos PDF linked from the results page, if any.

    Allowlisted, not just "not blocked": only a link naming RES_INFORMACION_DE_POZOS is
    returned. The same row of links carries the DET_INVALIDAS files, and a looser rule
    (e.g. "any PDF under /invalidas/") would pick those up the day the site reorders them.
    """
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if POZOS_PATTERN in href.upper() and blocked_pattern(href) is None:
            return urljoin(BASE_URL + "/", href)
    return None


def classify_extracto_php(content: bytes, day: date) -> Classification:
    text = BeautifulSoup(_decode(content), "html.parser").get_text(" ")
    match = _HEADER_DATE.search(text)
    if match:
        dd, mm, yyyy = (int(g) for g in match.groups())
        try:
            found = date(yyyy, mm, dd)
        except ValueError:
            return Classification(ERROR, detail=f"invalid header date {match.group(0)}")
        if found != day:
            return Classification(ERROR, detail=f"header dated {found.isoformat()}")
        return Classification(DRAW)
    if _EMPTY_DATE.search(text):
        return Classification(EMPTY)
    return Classification(ERROR, detail="no header date and no empty-template marker")


def classify_pdf(status: int, content: bytes) -> Classification:
    if status == 200 and content.startswith(b"%PDF"):
        return Classification(DRAW)
    if status == 404:
        return Classification(EMPTY)
    return Classification(ERROR, detail=f"HTTP {status}, {len(content)} bytes, not a PDF")
