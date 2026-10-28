"""The ver_resultados parser: real pages (tests/fixtures/uy/README.md) and mutations of them."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from sorteos.uy.parsers import common
from sorteos.uy.parsers import resultados as r

UY = Path(__file__).parents[2] / "fixtures" / "uy"
JULY_6 = date(2016, 7, 6)


def page(day: date, content: bytes | None = None) -> r.ParsedPage:
    if content is None:
        content = (UY / f"resultados_{day.isoformat()}.html").read_bytes()
    return r.parse(content, day)


def draw(parsed: r.ParsedPage, game: str) -> r.ParsedDraw:
    (found,) = (d for d in parsed.draws if d.game == game)
    return found


def numbers(parsed_draw: r.ParsedDraw, ball_type: str) -> list[str]:
    return [b.number for b in parsed_draw.numbers if b.ball_type == ball_type]


def mutate(old: str, new: str, *, day: date = JULY_6, count: int = 1) -> bytes:
    html = (UY / f"resultados_{day.isoformat()}.html").read_text("utf-8")
    assert old in html
    return html.replace(old, new, count).encode()


# --- one page, three games -------------------------------------------------------------------


def test_a_page_with_three_games_gives_three_draws():
    parsed = page(JULY_6)
    assert parsed.parser_version == 1 and parsed.failed == () and parsed.skipped == ()
    assert [d.game for d in parsed.draws] == [
        "quiniela_vespertina",
        "quiniela_nocturna",
        "5_de_oro",
    ]


def test_the_quiniela_position_comes_from_its_image_not_from_the_html_order():
    # The HTML interleaves positions 1, 11, 2, 12…: reading in order would scramble them.
    vespertina = draw(page(JULY_6), "quiniela_vespertina")
    quiniela = [b for b in vespertina.numbers if b.ball_type == "quiniela"]
    assert [b.position for b in quiniela] == list(range(1, 21))
    assert (quiniela[0].number, quiniela[1].number, quiniela[10].number) == ("316", "451", "661")
    assert quiniela[19].number == "039"  # zeros kept
    tombola = numbers(vespertina, "tombola")
    assert len(tombola) == 20 and (tombola[0], tombola[-1]) == ("04", "98")
    assert (vespertina.next_draw_text, vespertina.next_draw_date) == (
        "07 / 07 / 2016",
        date(2016, 7, 7),
    )


def test_the_5_de_oro_gives_its_numbers_and_three_prizes():
    oro = draw(page(JULY_6), "5_de_oro")
    assert numbers(oro, "oro") == ["01", "05", "17", "35", "36"]
    assert numbers(oro, "extra") == ["25"]
    assert numbers(oro, "revancha") == ["07", "33", "34", "44", "45"]
    assert oro.prizes == (
        r.Prize("oro", Decimal("35409043.86"), r.WINNERS, 2),
        r.Prize("plata", Decimal("491571.60"), r.WINNERS, 1),
        r.Prize("revancha", Decimal("8900914.00"), r.NO_WINNERS, 0),
    )
    assert oro.next_draw_date == date(2016, 7, 10)


def test_coupon_numbers_are_counted_and_never_returned():
    parsed = page(date(2025, 2, 9))
    assert draw(parsed, "5_de_oro").prizes[1].winning_coupons == 6
    assert "000000" not in repr(parsed)  # the fixture's fake coupons all start with it


def test_a_repeated_quiniela_number_keeps_both_positions():
    vespertina = draw(page(date(2023, 9, 29)), "quiniela_vespertina")
    quiniela = numbers(vespertina, "quiniela")
    assert len(quiniela) == 20 and len(set(quiniela)) < 20  # D3: the key is the position


# --- dirty data comes back as published -------------------------------------------------------


def test_empty_pools_and_empty_winner_cells_are_null_never_zero():
    oro = draw(page(date(2006, 8, 20)), "5_de_oro")
    assert {p.prize: (p.pool_amount, p.winners_status, p.winning_coupons) for p in oro.prizes} == {
        "oro": (None, r.UNKNOWN, None),
        "plata": (None, r.UNKNOWN, None),
        "revancha": (None, r.UNKNOWN, None),
    }
    assert (oro.next_draw_text, oro.next_draw_date) == (None, None)


def test_a_plata_pool_equal_to_oro_is_kept_as_published():
    oro = draw(page(date(2006, 12, 6)), "5_de_oro")
    assert oro.prizes[0].pool_amount == oro.prizes[1].pool_amount == Decimal("12022391.73")


def test_a_repeated_tombola_number_of_2006_is_kept_as_published():
    nocturna = draw(page(date(2006, 8, 31)), "quiniela_nocturna")
    tombola = numbers(nocturna, "tombola")
    assert len(tombola) == 20 and len(set(tombola)) < 20


def test_a_proximo_with_a_three_digit_year_keeps_its_text_and_no_date():
    nocturna = draw(page(date(2023, 9, 29)), "quiniela_nocturna")
    assert (nocturna.next_draw_text, nocturna.next_draw_date) == ("30 / 09 / 203", None)


def test_a_proximo_with_a_repeated_separator_is_read():
    oro = draw(page(date(2025, 2, 9)), "5_de_oro")
    assert (oro.next_draw_text, oro.next_draw_date) == ("12 / /02 / 2025", date(2025, 2, 12))


def test_an_empty_proximo_is_null():
    nocturna = draw(page(date(2006, 8, 11)), "quiniela_nocturna")
    assert (nocturna.next_draw_text, nocturna.next_draw_date) == (None, None)


# --- blocks v1 does not parse, and the "today" box --------------------------------------------


def test_loteria_and_kini_blocks_are_recognised_and_skipped():
    parsed = page(date(2010, 9, 3))
    assert parsed.skipped == ("loteria", "kini")
    assert [d.game for d in parsed.draws] == ["quiniela_vespertina", "quiniela_nocturna"]
    assert page(date(2006, 8, 11)).skipped == ("loteria",)


def test_the_loteria_codes_of_2018_onwards_are_loteria_too():
    # Codes 27-38 (UY-006): without them in site.yaml, 15 days went to quarantine whole.
    parsed = page(date(2018, 12, 29))
    assert parsed.skipped == ("loteria",)
    assert [d.game for d in parsed.draws] == ["quiniela_nocturna"]


def test_a_page_with_a_single_block():
    parsed = page(date(2026, 10, 3))
    assert [d.game for d in parsed.draws] == ["quiniela_nocturna"]


def test_the_today_box_is_ignored_even_on_the_day_of_the_draw():
    # Fetched on the day itself, the "Sorteos para el día de hoy" box carries the same date.
    same_day = mutate("Domingo 4 de Octubre de 2026", "Mi&eacute;rcoles 06 de Julio de 2016")
    assert page(JULY_6, same_day) == page(JULY_6)


# --- the whole day goes to quarantine ---------------------------------------------------------


@pytest.mark.parametrize(
    ("day", "content", "problem"),
    [
        (date(2019, 9, 25), None, "1 block headers for 0 extract links"),  # the AFAL strike
        (date(2025, 12, 25), None, "no game blocks"),
        (JULY_6, mutate("MostrarExtracto('5','06'", "MostrarExtracto('99','06'"), "code 99"),
        (JULY_6, mutate("MostrarExtracto('3','06'", "MostrarExtracto('4','06'"), "appears twice"),
        (JULY_6, mutate("MostrarExtracto('5','06'", "MostrarExtracto('5','07'"), "dated"),
    ],
)
def test_a_page_that_cannot_be_trusted_raises(day, content, problem):
    with pytest.raises(r.PageError, match=problem):
        page(day, content)


def test_a_day_before_the_first_parser_epoch_raises():
    with pytest.raises(r.PageError, match="no parser epoch"):
        page(date(2006, 8, 10), b"")


def test_an_extract_link_outside_any_block_raises():
    html = b"<img src='logo_5deoro.png'><a onclick=\"MostrarExtracto('5','06','07','2016')\">x</a>"
    with pytest.raises(r.PageError, match="no block of its own"):
        page(JULY_6, html)


# --- one draw goes to quarantine, the others still parse --------------------------------------


@pytest.mark.parametrize(
    ("old", "new", "game", "problem"),
    [
        (
            "06 de Julio de 2016",
            "07 de Julio de 2016",
            "quiniela_vespertina",
            "block dated",
        ),
        (
            "06 de Julio de 2016",
            "06 de Juliember de 2016",
            "quiniela_vespertina",
            "no block date",
        ),
        (
            "Próximo  Vespertino:",
            "Siguiente:",
            "quiniela_vespertina",
            "expected 'Próximo Vespertino'",
        ),
        ("l_11.gif", "l_01.gif", "quiniela_vespertina", "quiniela positions"),
        ("316", "31", "quiniela_vespertina", "quiniela number '31' is not 3 digits"),
        ("Pozo de Plata: $", "Pozo Plata", "5_de_oro", "'Pozo de Plata: \\$' appears 0 times"),
        ("35,409,043.86", "35.409.043,86", "5_de_oro", "not a us amount"),
        ("Sin Aciertos", "Quizás", "5_de_oro", "revancha: winners cell not understood"),
    ],
)
def test_a_block_with_another_shape_fails_alone(old, new, game, problem):
    parsed = page(JULY_6, mutate(old, new))
    (failed,) = parsed.failed
    assert failed.game == game and failed.draw_date == JULY_6
    assert re.search(problem, failed.reason), failed.reason
    assert len(parsed.draws) == 2


def test_a_block_is_found_through_nested_tables_and_an_empty_one_fails():
    # Real blocks hold their header in the first table up; a deeper link must still find it.
    html = (
        b"<table><tr><td><img src='logo_5deoro.png'></td></tr><tr><td>"
        b"<table><tr><td><a onclick=\"MostrarExtracto('5','06','07','2016')\">x</a></td></tr>"
        b"</table></td></tr></table>"
    )
    assert page(JULY_6, html).failed == (r.FailedDraw("5_de_oro", JULY_6, "empty block"),)


def test_a_number_with_the_wrong_digits_fails():
    with pytest.raises(r.BlockError, match="tombola number '4' is not 2 digits"):
        common.balls("tombola", ["4"] * 20, "quiniela_nocturna")


def test_a_quiniela_published_without_its_tombola_is_still_a_draw():
    # The one Vespertina of 2006-08-31 (owner, UY-022): 20 Quiniela numbers, no Tómbola rows.
    parsed = page(date(2006, 8, 31))
    assert parsed.failed == ()
    vespertina = draw(parsed, "quiniela_vespertina")
    assert len(numbers(vespertina, "quiniela")) == 20 and numbers(vespertina, "tombola") == []


def test_a_partial_tombola_still_fails():
    with pytest.raises(r.BlockError, match="19 tombola numbers, expected 20"):
        common.quiniela("quiniela_nocturna", [(i, f"{i:03d}") for i in range(1, 21)], ["01"] * 19)


def test_a_proximo_written_like_a_block_header_is_read():
    # The 5 de Oro of 2006-08-23 announces "Domingo 3 de Setiembre de 2006" (owner, UY-022).
    assert common.next_draw(
        "Próximo 5 de Oro y Rev.: Domingo 3 de Setiembre de 2006",
        common.CONFIG.games["5_de_oro"].calendar.next_draw_label,
    ) == ("Domingo 3 de Setiembre de 2006", date(2006, 9, 3))
    assert common.long_date("Domingo 31 de Setiembre de 2006") is None


def test_the_pool_labels_must_be_in_page_order():
    body = [(t, None) for t in ["Pozo de Plata: $", "Pozo de Oro: $", "Pozo Revancha: $"]]
    with pytest.raises(r.BlockError, match="out of order"):
        r._cinco_de_oro(body)


# --- the winners cell, as typed over 20 years -------------------------------------------------


@pytest.mark.parametrize(
    ("cell", "status", "coupons"),
    [
        ([], r.UNKNOWN, None),
        (["Sin Aciertos"], r.NO_WINNERS, 0),
        (["sin acierto"], r.NO_WINNERS, 0),
        (["SIN ACIERTO"], r.NO_WINNERS, 0),
        (["SIn Aciertos"], r.NO_WINNERS, 0),
        (["SinAciertos"], r.NO_WINNERS, 0),
        (["Sin Acierrtos"], r.NO_WINNERS, 0),
        (["Sin Aiciertos"], r.NO_WINNERS, 0),
        (["si aciertos"], r.NO_WINNERS, 0),
        (["Vacante"], r.NO_WINNERS, 0),
        (["000000001-0"], r.WINNERS, 1),
        (["00000001-0-0", "0000000002-0-0"], r.WINNERS, 2),
        (["000000001-0|", "0000000002"], r.WINNERS, 2),
        (["00000000001"], r.WINNERS, 1),
    ],
)
def test_the_winners_cell(cell, status, coupons):
    prize = r._prize("oro", cell)
    assert (prize.winners_status, prize.winning_coupons, prize.pool_amount) == (
        status,
        coupons,
        None,
    )


@pytest.mark.parametrize(
    "cell", [["Sin Aciertos", "000000001-0"], ["Quizás"], ["000000001-0", "12"], ["Aciertos"]]
)
def test_a_winners_cell_that_is_not_understood_fails(cell):
    with pytest.raises(r.BlockError, match="winners cell not understood"):
        r._prize("oro", cell)


def test_the_amount_comes_first_in_the_cell():
    assert r._prize("plata", ["491,571.60", "000000001-0"]) == r.Prize(
        "plata", Decimal("491571.60"), r.WINNERS, 1
    )
