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

Since UY-020 the paths, query parameters, start dates and game codes come from
``site.yaml`` and ``games/*.yaml`` (docs/uruguay/DESIGN.md, D4): this module only turns them
into URLs. The source **names** are the manifest's key, so they never change — renaming one
would orphan its rows and make the backfill fetch everything again.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sorteos.core.config import load_country

CONFIG = load_country(Path(__file__).parent)

BASE_URL = CONFIG.site.base_url
COUNTRY = CONFIG.site.country  # ISO 3166-1 alpha-2, lower case (DESIGN.md, D1)
# How the DNLQ has seen us since UY-001 (in its access logs): keep it stable.
AGENT = "loteria-uy-research/0.1"

# Game names the code branches on (classify.py maps block images to them). The YAML is
# what defines them; the checks below make a rename there fail at import, not at run time.
ORO = "5_de_oro"
QV = "quiniela_vespertina"
QN = "quiniela_nocturna"
LOTERIA = "loteria"
KINI = "kini"
QVN = "quiniela_vn"

# The order sources are requested in, which the YAML file names would not keep.
_V1_GAMES = (ORO, QV, QN)
if set(_V1_GAMES) != set(CONFIG.games):  # pragma: no cover — a broken checkout, not a test
    raise RuntimeError(f"games/*.yaml declares {sorted(CONFIG.games)}, the code knows {_V1_GAMES}")
if not {LOTERIA, KINI, QVN} <= set(CONFIG.site.other_games):  # pragma: no cover
    raise RuntimeError(f"site.yaml other_games lacks one of {LOTERIA}, {KINI}, {QVN}")

_GAME_BY_CODE = {game.site_code: name for name, game in CONFIG.games.items()} | {
    code: name for name, codes in CONFIG.site.other_games.items() for code in codes
}


def game_for_code(code: int) -> str:
    return _GAME_BY_CODE.get(code, f"unknown_{code}")


_EXTENSIONS = {
    "resultados": "html",
    "extracto_php": "html",
    "extracto_pdf": "pdf",
    "pozos_pdf": "pdf",
}


@dataclass(frozen=True)
class Source:
    name: str
    game: str | None  # None for the multi-game results page
    kind: str  # "resultados" | "extracto_php" | "extracto_pdf" | "pozos_pdf"
    extension: str
    path: str | None = None  # a template; None when the URL comes from a page's link
    params: tuple[tuple[str, str], ...] = ()  # (name, template), in the order the site uses
    valid_from: date | None = None

    def url(self, day: date) -> str:
        if self.path is None:
            raise ValueError(f"{self.name}: URL comes from the results page, not from a date")
        fields = {"day": day.day, "month": day.month, "year": day.year}
        url = BASE_URL + self.path.format(**fields)
        if self.params:
            # Built by hand, not urlencoded: the values are digits and the site's own links
            # use exactly this shape.
            url += "?" + "&".join(f"{k}={v.format(**fields)}" for k, v in self.params)
        return url

    def applies_to(self, day: date) -> bool:
        return self.valid_from is None or day >= self.valid_from


_page = CONFIG.site.pages["resultados"]
RESULTADOS = Source(
    "resultados", None, "resultados", "html", _page.path, tuple(_page.params.items())
)


def _game_sources(kind: str) -> tuple[Source, ...]:
    return tuple(
        Source(
            spec.name,
            game,
            kind,
            _EXTENSIONS[kind],
            spec.path,
            tuple(spec.params.items()),
            spec.valid_from,
        )
        for game in _V1_GAMES
        for spec in CONFIG.games[game].sources
        if spec.kind == kind
    )


EXTRACTOS_PHP = _game_sources("extracto_php")
EXTRACTOS_PDF = _game_sources("extracto_pdf")
# The 5 de Oro pozos PDF. Its folder mixes date formats (ddmmyyyy for Oro), so its URL is
# taken from the results page's own link instead of being rebuilt — see classify.pozos_href.
(POZOS,) = _game_sources("pozos_pdf")

ALL_SOURCES = {s.name: s for s in (RESULTADOS, *EXTRACTOS_PHP, *EXTRACTOS_PDF, POZOS)}

# Named groups for the CLI.
SOURCE_GROUPS = {
    "resultados": (RESULTADOS,),
    "extractos": EXTRACTOS_PHP,
    "pdf": EXTRACTOS_PDF,
    "pozos": (POZOS,),
}
