"""The PHP extract parsers and their cross-check against ver_resultados (fixtures: README.md)."""

from __future__ import annotations

import dataclasses
import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from sorteos.uy.parsers import common, cross_check, resultados
from sorteos.uy.parsers import extracto_5_de_oro as oro
from sorteos.uy.parsers import extracto_quiniela as quiniela

UY = Path(__file__).parents[2] / "fixtures" / "uy"
QV, QN = "quiniela_vespertina", "quiniela_nocturna"


def read(name: str) -> bytes:
    return (UY / f"{name}.html").read_bytes()


def mutate(name: str, old: str, new: str) -> bytes:
    html = read(name).decode("utf-8")
    assert old in html
    return html.replace(old, new, 1).encode()


def numbers(draw: common.ParsedDraw, ball_type: str) -> list[str]:
    return [b.number for b in draw.numbers if b.ball_type == ball_type]


def primary(day: date, game: str) -> common.ParsedDraw:
    (found,) = (d for d in resultados.parse(read(f"resultados_{day}"), day).draws if d.game == game)
    return found


# --- the Quiniela extract ---------------------------------------------------------------------


def test_the_quiniela_extract_gives_numbers_by_position_and_three_times():
    draw = quiniela.parse(read("extracto_quiniela_vespertina_2007-01-02"), date(2007, 1, 2), QV)
    quiniela_numbers = [b for b in draw.numbers if b.ball_type == "quiniela"]
    assert [b.position for b in quiniela_numbers] == list(range(1, 21))
    assert [quiniela_numbers[i].number for i in (0, 1, 10, 19)] == ["701", "449", "099", "854"]
    assert len(numbers(draw, "tombola")) == 20
    assert (draw.started_local, draw.first_ball_local, draw.ended_local) == (
        datetime(2007, 1, 2, 15, 0),
        datetime(2007, 1, 2, 15, 11),
        datetime(2007, 1, 2, 15, 19),
    )
    assert (draw.next_draw_text, draw.next_draw_date) == ("03 / 01 / 2007", date(2007, 1, 3))
    assert draw.prizes == ()


def test_empty_times_are_null_and_a_missing_tombola_has_no_rows():
    # The Vespertina of 2006-08-31: "hrs." with no time, and no Tómbola (owner, UY-022).
    draw = quiniela.parse(read("extracto_quiniela_vespertina_2006-08-31"), date(2006, 8, 31), QV)
    assert (draw.started_local, draw.first_ball_local, draw.ended_local) == (None, None, None)
    assert len(numbers(draw, "quiniela")) == 20 and numbers(draw, "tombola") == []


def test_times_out_of_order_are_kept_as_published():
    # The Nocturna of 2009-08-01 ends at 15:24 after starting at 21:00; UY-025 flags it.
    draw = quiniela.parse(read("extracto_quiniela_nocturna_2009-08-01"), date(2009, 8, 1), QN)
    assert draw.started_local == datetime(2009, 8, 1, 21, 0)
    assert draw.ended_local == datetime(2009, 8, 1, 15, 24)


@pytest.mark.parametrize(
    ("old", "new", "problem"),
    [
        ("Martes 02/01/2007", "Martes 03/01/2007", "extract dated 'Martes 03/01/2007'"),
        ("Martes 02/01/2007", "Martes", "no header date"),
        ("Primero", "Segundo", "expected \\('Inicio', 'Primero', 'Fin'\\)"),
        ("15:11 hrs.", "a las 15:11", "is not a time"),
        ("15:11 hrs.", "25:11 hrs.", "is not a time of day"),
        ("Próximo Sorteo:", "Siguiente:", "0 'Próximo Sorteo' lines"),
        ("p_11.gif", "p_1.gif", "quiniela positions"),
    ],
)
def test_a_quiniela_extract_with_another_shape_fails(old, new, problem):
    content = mutate("extracto_quiniela_vespertina_2007-01-02", old, new)
    with pytest.raises(common.BlockError, match=problem):
        quiniela.parse(content, date(2007, 1, 2), QV)


def test_the_empty_quiniela_template_is_not_a_draw():
    with pytest.raises(common.BlockError, match="no header date"):
        # Dated inside the epoch on purpose: the template itself carries no date at all.
        quiniela.parse(read("extracto_quiniela_nocturna_2006-08-10"), date(2007, 1, 2), QN)


def test_only_quinielas_and_only_dated_epochs():
    with pytest.raises(ValueError, match="not a Quiniela"):
        quiniela.parse(b"", date(2007, 1, 2), "5_de_oro")
    with pytest.raises(common.BlockError, match="no parser epoch"):
        quiniela.parse(b"", date(2006, 8, 10), QV)
    assert quiniela.parser_version(QN, date(2026, 10, 3)) == 1


# --- the 5 de Oro extract ---------------------------------------------------------------------


def test_the_5_de_oro_extract_reads_numbers_pools_and_winners_by_cell():
    draw = oro.parse(read("extracto_5_de_oro_2007-01-07"), date(2007, 1, 7))
    assert numbers(draw, "oro") == ["09", "11", "15", "20", "35"]
    assert numbers(draw, "extra") == ["17"]
    assert numbers(draw, "revancha") == ["26", "28", "31", "33", "38"]
    assert draw.prizes == (
        common.Prize("oro", Decimal("2472229.46"), common.WINNERS, 2),
        common.Prize("plata", Decimal("122431.03"), common.NO_WINNERS, 0),
        common.Prize("revancha", Decimal("1838745.99"), common.NO_WINNERS, 0),
    )
    assert draw.next_draw_date == date(2007, 1, 10)
    assert "000000" not in repr(draw)  # coupons are counted, never returned


def test_empty_template_pools_and_empty_cells_are_null():
    # 2006-08-20: "0,00" pools and three empty cells. Read by text order, the empty Oro cell
    # would have taken Plata's content; read by cell, each stays empty.
    draw = oro.parse(read("extracto_5_de_oro_2006-08-20"), date(2006, 8, 20))
    assert {(p.pool_amount, p.winners_status, p.winning_coupons) for p in draw.prizes} == {
        (None, common.UNKNOWN, None)
    }


@pytest.mark.parametrize(
    ("old", "new", "problem"),
    [
        ("Bolilla Extra:", "Extra:", "not followed by 'Bolilla Extra:'"),
        ("2.472.229,46", "2,472,229.46", "0 pool amounts|2 pool amounts"),
        ("122.431,03", "1.22.431,03", "not a uy amount"),
        ("Próximo Sorteo:", "Siguiente:", "0 'Próximo Sorteo' lines"),
        ("SIN ACIERTO", "QUIZÁS", "plata: winners cell not understood"),
    ],
)
def test_a_5_de_oro_extract_with_another_shape_fails(old, new, problem):
    with pytest.raises((common.BlockError, ValueError), match=problem):
        oro.parse(mutate("extracto_5_de_oro_2007-01-07", old, new), date(2007, 1, 7))


def test_a_5_de_oro_extract_needs_its_eleven_numbers_and_two_winners_tables():
    one_less = mutate(
        "extracto_5_de_oro_2007-01-07",
        'valign="middle" class="Estilo_aproximaciones_nro">  09',
        'valign="middle">  09',
    )
    with pytest.raises(common.BlockError, match="10 numbers"):
        oro.parse(one_less, date(2007, 1, 7))
    html = read("extracto_5_de_oro_2007-01-07").decode("utf-8")
    no_tables = html.replace("Cupón Nro:", "")
    with pytest.raises(common.BlockError, match="0 winners tables"):
        oro.parse(no_tables.encode(), date(2007, 1, 7))
    no_plata_cell = re.sub(
        r'<td align="right" valign="top" class="Estilo_terminaciones_txt">\s*SIN ACIERTO\s*</td>',
        "",
        html,
        count=1,
    )
    with pytest.raises(common.BlockError, match="1 winners cells for \\('oro', 'plata'\\)"):
        oro.parse(no_plata_cell.encode(), date(2007, 1, 7))


def test_the_empty_5_de_oro_template_is_not_a_draw():
    with pytest.raises(common.BlockError, match="no header date"):
        oro.parse(read("extracto_5_de_oro_2025-09-16"), date(2025, 9, 16))


def test_a_day_before_the_5_de_oro_epoch_fails():
    with pytest.raises(common.BlockError, match="no parser epoch"):
        oro.parse(b"", date(2006, 8, 10))
    assert oro.parser_version(date(2026, 10, 18)) == 1


# --- the cross-check --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("day", "game", "extract"),
    [
        (date(2006, 8, 20), "5_de_oro", lambda d: oro.parse(read(f"extracto_5_de_oro_{d}"), d)),
        (date(2025, 2, 9), "5_de_oro", lambda d: oro.parse(read(f"extracto_5_de_oro_{d}"), d)),
        (
            date(2006, 8, 31),
            QV,
            lambda d: quiniela.parse(read(f"extracto_quiniela_vespertina_{d}"), d, QV),
        ),
    ],
)
def test_both_sources_agree_on_the_fixtures(day, game, extract):
    assert cross_check.compare(primary(day, game), extract(day)) == ()


def test_every_kind_of_difference_is_reported():
    mine = primary(date(2025, 2, 9), "5_de_oro")
    oro_prize, plata, revancha = mine.prizes
    other = dataclasses.replace(
        mine,
        numbers=(dataclasses.replace(mine.numbers[0], number="02"), *mine.numbers[1:]),
        next_draw_text="13 / 02 / 2025",
        next_draw_date=date(2025, 2, 13),
        prizes=(
            dataclasses.replace(oro_prize, pool_amount=Decimal("1.00")),
            dataclasses.replace(plata, winning_coupons=5),
            common.Prize("bonus", None, common.UNKNOWN, None),
        ),
    )
    fields = [d.field for d in cross_check.compare(mine, other)]
    assert fields == [
        "numbers:oro",
        "next_draw",
        "pool_amount:oro",
        "winners:plata",
        "winners:revancha",
        "winners:bonus",
    ]
    (number,) = (d for d in cross_check.compare(mine, other) if d.field == "numbers:oro")
    assert number.primary[0] == (1, "01") and number.other[0] == (1, "02")


def test_an_unparsed_proximo_is_compared_by_its_text():
    mine = primary(date(2023, 9, 29), QN)  # "30 / 09 / 203": no date
    same = dataclasses.replace(mine, next_draw_text="30  /  09 / 203")
    other = dataclasses.replace(mine, next_draw_text="30 / 09 / 204")
    assert cross_check.compare(mine, same) == ()
    assert [d.field for d in cross_check.compare(mine, other)] == ["next_draw"]


def test_two_different_draws_are_not_compared():
    mine = primary(date(2025, 2, 9), "5_de_oro")
    with pytest.raises(ValueError, match="not the same draw"):
        cross_check.compare(mine, dataclasses.replace(mine, draw_date=date(2025, 2, 12)))
