"""UY-030.2: the ``ver_estadisticas`` answers, read from real pages and broken ones."""

from __future__ import annotations

from pathlib import Path

import pytest

from sorteos.uy.parsers import estadisticas as e

FIXTURES = Path(__file__).parents[2] / "fixtures" / "uy"


def fixture(name: str) -> e.Stats:
    return e.parse((FIXTURES / f"estadisticas_{name}.html").read_bytes())


def test_the_5_de_oro_page_has_a_grid_for_the_5_de_oro_and_one_for_the_revancha():
    stats = fixture("5_de_oro_2006-01-01_2026-10-28")
    # 2,080 draws, each counted once as 5 de Oro and once as Revancha, plus the Revancha the
    # site also stores under 2010-10-07 (FINDINGS, Q10).
    assert stats.consulted == 2 * 2080 + 1
    oro, revancha = stats.grids["5 de Oro"], stats.grids["Revancha"]
    assert (len(oro), sum(oro.values())) == (48, 5 * 2080)  # never the extra ball
    assert (len(revancha), sum(revancha.values())) == (48, 5 * 2081)
    assert list(stats.grids) == ["5 de Oro", "Revancha"]


def test_the_quiniela_page_lists_3_digit_numbers_under_the_hundreds():
    stats = fixture("quiniela_pos01_2025")  # position 1 of 2025: the 249 Vespertinas
    (grid,) = stats.grids.values()
    assert stats.consulted == 249
    assert (len(grid), sum(grid.values())) == (225, 249)
    assert grid["073"] == 2 and "73" not in grid
    assert list(stats.grids) == [e.UNTITLED]


def test_the_tombola_page_counts_every_number_with_its_replacements():
    stats = fixture("tombola_2007-01-01_2026-10-30")
    (grid,) = stats.grids.values()
    assert stats.consulted == 4869
    assert (len(grid), sum(grid.values())) == (100, 20 * 4869)


def page(*cells: str, consulted: int = 2, footer: bool = True) -> bytes:
    rows = "".join(f"<tr><td>{c}</td></tr>" for c in cells)
    return (
        "<html><body><table><tr><td>Total: 9</td></tr>"
        f"<tr><td><span>Cantidad de sorteos consultados:&nbsp;</span>&nbsp;{consulted}</td></tr>"
        f"<tr><td><table>{rows}</table></td></tr>"
        + ("<tr><td>Transparencia</td></tr>" if footer else "")
        + "</table></body></html>"
    ).encode()


def test_headers_and_empty_cells_are_skipped_and_the_footer_ends_the_results():
    stats = e.parse(page("0<br/>", "Número", "Veces", "&nbsp;", "07", "2&nbsp;", "1", "15", "3"))
    assert stats.grids == {e.UNTITLED: {"07": 2, "15": 3}}


def test_an_empty_answer_is_a_form_without_numbers():
    assert e.parse(page("Número", "Veces", consulted=0)).grids == {}


@pytest.mark.parametrize(
    ("cells", "consulted", "message"),
    [
        (("07", "Número"), 2, "number 07 without a count"),
        (("07", "1", "07", "1"), 2, "07 listed twice"),
        (("07", "1", "107", "1"), 2, "mixes \\[2, 3\\]-digit numbers"),
        (("Número", "Veces"), 2, "2 draws consulted and no number listed"),
    ],
)
def test_a_page_out_of_shape_raises(cells, consulted, message):
    with pytest.raises(e.StatsError, match=message):
        e.parse(page(*cells, consulted=consulted))


def test_a_page_cut_after_a_number_raises():
    with pytest.raises(e.StatsError, match="number 07 without a count at the end"):
        e.parse(page("07", footer=False))


def test_a_page_that_is_not_an_answer_raises():
    with pytest.raises(e.StatsError, match="no 'Cantidad de sorteos consultados'"):
        e.parse(b"<html><body><table><tr><td>Mantenimiento</td></tr></table></body></html>")
