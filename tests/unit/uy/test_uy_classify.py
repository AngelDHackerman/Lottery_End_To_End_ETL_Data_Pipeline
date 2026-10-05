"""Draw / empty / error decisions against real pages (fetched 2026-10-04)."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from loteria_uy import classify, sources
from loteria_uy.classify import DRAW, EMPTY, ERROR

UY = Path(__file__).parents[2] / "fixtures" / "uy"


def page(name: str) -> bytes:
    return (UY / name).read_bytes()


@pytest.mark.parametrize(
    ("name", "day", "games"),
    [
        ("resultados_2006-08-11.html", date(2006, 8, 11), ("loteria", "quiniela_nocturna")),
        (
            "resultados_2010-09-03.html",
            date(2010, 9, 3),
            ("loteria", "quiniela_vespertina", "quiniela_nocturna", "kini"),
        ),
        (
            "resultados_2016-07-06.html",
            date(2016, 7, 6),
            ("quiniela_vespertina", "quiniela_nocturna", "5_de_oro"),
        ),
        ("resultados_2026-10-03.html", date(2026, 10, 3), ("quiniela_nocturna",)),
    ],
)
def test_results_pages_list_the_games_drawn_that_day(name, day, games):
    verdict = classify.classify_resultados(page(name), day)
    assert verdict.outcome == DRAW
    assert verdict.games == games
    assert verdict.warnings == ()


def test_a_day_without_draws_is_empty():
    verdict = classify.classify_resultados(page("resultados_2025-12-25.html"), date(2025, 12, 25))
    assert verdict.outcome == EMPTY


def test_codes_dated_another_day_are_an_error_not_a_draw():
    verdict = classify.classify_resultados(page("resultados_2010-09-03.html"), date(2010, 9, 4))
    assert verdict.outcome == ERROR
    assert "2010-09-03" in verdict.detail


def test_the_pozos_link_is_picked_up_and_the_privacy_links_are_not():
    verdict = classify.classify_resultados(page("resultados_2016-07-06.html"), date(2016, 7, 6))
    assert verdict.extra == {
        "pozos_url": "https://www.loteria.gub.uy/invalidas/06072016/"
        "ORO_06072016_RES_INFORMACION_DE_POZOS.PDF"
    }


def test_a_block_image_without_its_code_raises_a_warning():
    html = page("resultados_2016-07-06.html").decode()
    html = re.sub(r"MostrarExtracto\('5',[^)]*\)", "", html)
    verdict = classify.classify_resultados(html.encode(), date(2016, 7, 6))
    assert verdict.outcome == DRAW
    assert verdict.warnings == ("marker_mismatch:5_de_oro",)


def test_block_images_with_no_codes_at_all_are_an_error():
    html = re.sub(
        r"MostrarExtracto\('\d+',[^)]*\)", "", page("resultados_2010-09-03.html").decode()
    )
    verdict = classify.classify_resultados(html.encode(), date(2010, 9, 3))
    assert verdict.outcome == ERROR


def test_pozos_href_is_an_allowlist():
    soup = BeautifulSoup(
        '<a href="invalidas/1/X_DET_INVALIDAS_RES_INFORMACION_DE_POZOS.PDF">a</a>'
        '<a href="invalidas/1/other.pdf">b</a>',
        "html.parser",
    )
    assert classify.pozos_href(soup) is None


def test_php_extract_with_a_draw():
    verdict = classify.classify_extracto_php(
        page("extracto_5_de_oro_2007-01-07.html"), date(2007, 1, 7)
    )
    assert verdict.outcome == DRAW
    verdict = classify.classify_extracto_php(
        page("extracto_quiniela_vespertina_2007-01-02.html"), date(2007, 1, 2)
    )
    assert verdict.outcome == DRAW


def test_php_extract_empty_template():
    verdict = classify.classify_extracto_php(
        page("extracto_5_de_oro_2025-09-16.html"), date(2025, 9, 16)
    )
    assert verdict.outcome == EMPTY


def test_php_extract_for_another_day_is_an_error():
    verdict = classify.classify_extracto_php(
        page("extracto_5_de_oro_2007-01-07.html"), date(2007, 1, 10)
    )
    assert verdict.outcome == ERROR
    assert "2007-01-07" in verdict.detail


@pytest.mark.parametrize(
    "body",
    [b"<html>Martes 31/02/2007</html>", b"<html>nothing here</html>", b"see https://x.org/"],
)
def test_php_extract_that_is_neither_is_an_error(body):
    assert classify.classify_extracto_php(body, date(2007, 2, 28)).outcome == ERROR


@pytest.mark.parametrize(
    ("status", "body", "outcome"),
    [
        (200, b"%PDF-1.7 ...", DRAW),
        (404, b"<html>404</html>", EMPTY),
        (200, b"<html>not a pdf</html>", ERROR),
        (403, b"", ERROR),
    ],
)
def test_pdf_outcomes(status, body, outcome):
    assert classify.classify_pdf(status, body).outcome == outcome


@pytest.mark.parametrize(
    ("code", "game"),
    [
        (1, "loteria"),
        (2, "kini"),
        (3, "quiniela_vespertina"),
        (4, "quiniela_nocturna"),
        (5, "5_de_oro"),
        (6, "loteria"),
        (19, "quiniela_vn"),
        (26, "loteria"),
        (27, "unknown_27"),
    ],
)
def test_game_codes(code, game):
    assert sources.game_for_code(code) == game


def test_source_urls():
    day = date(2007, 1, 2)
    assert sources.RESULTADOS.url(day).endswith("ver_resultados.php?vdia=2&vmes=1&vano=2007")
    php = {s.game: s.url(day) for s in sources.EXTRACTOS_PHP}
    assert php["quiniela_nocturna"].endswith("extracto_QN_S.php?vdia=02&vmes=01&vano=2007")
    pdf = {s.game: s for s in sources.EXTRACTOS_PDF}
    assert pdf["5_de_oro"].url(date(2025, 9, 17)).endswith("/extractosweb/20250917o.pdf")
    assert not pdf["5_de_oro"].applies_to(date(2018, 11, 29))
    assert pdf["5_de_oro"].applies_to(date(2018, 11, 30))
    with pytest.raises(ValueError):
        sources.POZOS.url(day)
