"""Where each raw page lives, per source and draw date.

Everything here was observed against www.loteria.gub.uy on 2026-10-04 (see
docs/uruguay/FINDINGS.md). Two layers:

- **resultados** — ``ver_resultados.php``, one page per calendar day with every game drawn
  that day. It is the discovery layer: the other sources are only requested for the games
  this page says were drawn.
- **extractos** — the official per-game extract. Two shapes exist side by side:
    * the PHP page (``extractosweb/.../*.php``), which answers for every year back to 2006,
      always with HTTP 200 — an empty template when there was no draw;
    * the static PDF (``extractosweb/{yyyymmdd}{letter}.pdf``), which the site's own
      ``MostrarExtracto()`` switches to from 2018-11-30. It answers 404 when there was no
      draw and carries a ``Last-Modified`` close to the publication time.

Game codes are the first argument of ``MostrarExtracto('<code>', dd, mm, yyyy)`` in the
results page — the site's own routing table, which makes them a sturdier signal than the
block images (kept as a cross-check in classify.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

BASE_URL = "https://www.loteria.gub.uy"

# The day MostrarExtracto() starts serving the PDF instead of the PHP extract.
PDF_EXTRACTS_FROM = date(2018, 11, 30)

# Games in scope for v1 (roadmap-uruguay.md). Lotería and Kini are recorded when the
# results page shows them, but no per-game source is fetched for them yet.
ORO = "5_de_oro"
QV = "quiniela_vespertina"
QN = "quiniela_nocturna"
LOTERIA = "loteria"
KINI = "kini"
QVN = "quiniela_vn"

# MostrarExtracto() codes -> game. 1 and 6..26 (except 19) are Lotería variants — the
# function maps each to a different yearly extract script (Gordo, Revancha, ...).
_FIXED_CODES = {2: KINI, 3: QV, 4: QN, 5: ORO, 19: QVN}


def game_for_code(code: int) -> str:
    if code in _FIXED_CODES:
        return _FIXED_CODES[code]
    if code == 1 or 6 <= code <= 26:
        return LOTERIA
    return f"unknown_{code}"


@dataclass(frozen=True)
class Source:
    name: str
    game: str | None  # None for the multi-game results page
    kind: str  # "resultados" | "extracto_php" | "extracto_pdf" | "pozos_pdf"
    extension: str

    def url(self, day: date) -> str:
        if self.kind == "resultados":
            # The site accepts and normalises unpadded values; keep them unpadded so the
            # URL matches what the page's own calendar links produce.
            return f"{BASE_URL}/ver_resultados.php?vdia={day.day}&vmes={day.month}&vano={day.year}"
        if self.kind == "extracto_php":
            query = f"?vdia={day.day:02d}&vmes={day.month:02d}&vano={day.year}"
            return BASE_URL + _PHP_PATHS[self.game] + query
        if self.kind == "extracto_pdf":
            return f"{BASE_URL}/extractosweb/{day:%Y%m%d}{_PDF_LETTERS[self.game]}.pdf"
        raise ValueError(f"{self.name}: URL comes from the results page, not from a date")

    def applies_to(self, day: date) -> bool:
        if self.kind == "extracto_pdf":
            return day >= PDF_EXTRACTS_FROM
        return True


_PHP_PATHS = {
    ORO: "/extractosweb/5deOro/extracto_5_de_oro.php",
    QV: "/extractosweb/quiniela/vespertina/extracto_QV_S.php",
    QN: "/extractosweb/quiniela/nocturna/extracto_QN_S.php",
}
# From MostrarExtracto(): 'o' for 5 de Oro, 'v' vespertina, 'n' nocturna ('l' is Lotería).
_PDF_LETTERS = {ORO: "o", QV: "v", QN: "n"}

RESULTADOS = Source("resultados", None, "resultados", "html")
EXTRACTOS_PHP = tuple(Source(f"extracto_{g}", g, "extracto_php", "html") for g in (ORO, QV, QN))
EXTRACTOS_PDF = tuple(Source(f"extracto_pdf_{g}", g, "extracto_pdf", "pdf") for g in (ORO, QV, QN))
# The 5 de Oro pozos PDF. Its folder mixes date formats (ddmmyyyy for Oro), so its URL is
# taken from the results page's own link instead of being rebuilt — see classify.pozos_href.
POZOS = Source("pozos_5_de_oro", ORO, "pozos_pdf", "pdf")

ALL_SOURCES = {s.name: s for s in (RESULTADOS, *EXTRACTOS_PHP, *EXTRACTOS_PDF, POZOS)}

# Named groups for the CLI.
SOURCE_GROUPS = {
    "resultados": (RESULTADOS,),
    "extractos": EXTRACTOS_PHP,
    "pdf": EXTRACTOS_PDF,
    "pozos": (POZOS,),
}
