"""D21: a draw's numbers against its YAML shape, with the range taken from game_rules."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from sorteos.core import shapes
from sorteos.uy.sources import CONFIG, ORO, QN

GAME_RULES = Path(shapes.__file__).parents[1] / "uy" / "reference" / "game_rules.csv"
RANGES = shapes.load_ranges(GAME_RULES, {(ORO, "rango_numeros")})
ORO_SHAPE = CONFIG.games[ORO].numbers
QN_SHAPE = CONFIG.games[QN].numbers


def oro(day=date(2016, 6, 1), oro=("05", "12", "20", "33", "48"), extra=("07",), revancha=None):
    numbers = {"oro": list(oro), "extra": list(extra), "revancha": list(revancha or oro)}
    return shapes.problems(ORO, day, ORO_SHAPE, numbers, RANGES)


def test_the_range_moves_with_game_rules_on_2014_03_19():
    assert RANGES[(ORO, "rango_numeros")] == [
        shapes.Range(1, 44, date(2006, 8, 16), date(2014, 3, 18)),
        shapes.Range(1, 48, date(2014, 3, 19), None),
    ]
    assert oro(date(2014, 3, 19)) == []
    assert oro(date(2014, 3, 16)) == [
        "oro ['48'] outside 01-44",
        "revancha ['48'] outside 01-44",
    ]


@pytest.mark.parametrize(
    ("changes", "problem"),
    [
        ({"oro": ("05", "12", "20", "48", "33")}, "oro is not sorted"),
        ({"oro": ("05", "12", "12", "33", "48")}, "oro repeats a number"),
        ({"extra": ("12",)}, "extra ['12'] is also in oro"),
        ({"extra": ("00",)}, "extra ['00'] outside 01-48"),
        ({"day": date(2006, 8, 15)}, "0 rango_numeros rows of 5_de_oro cover 2006-08-15"),
    ],
)
def test_what_breaks_the_shape_is_named(changes, problem):
    found = oro(**changes)
    assert found and found[0].startswith(problem)


def test_two_rows_covering_the_same_day_is_a_problem_too():
    overlapping = {(ORO, "rango_numeros"): [shapes.Range(1, 44, None, None)] * 2}
    numbers = {"extra": ["07"]}
    found = shapes.problems(ORO, date(2016, 6, 1), ORO_SHAPE, numbers, overlapping)
    assert found == ["2 rango_numeros rows of 5_de_oro cover 2016-06-01"]


def test_a_flagged_ball_type_may_repeat_and_an_empty_one_is_not_checked():
    tombola = sorted(["01", "01", *(f"{n:02d}" for n in range(2, 20))])
    numbers = {"quiniela": [], "tombola": tombola}
    assert shapes.problems(QN, date(2006, 8, 12), QN_SHAPE, numbers, {}) == [
        "tombola repeats a number: " + str(tombola)
    ]
    assert shapes.problems(QN, date(2006, 8, 12), QN_SHAPE, numbers, {}, {"tombola"}) == []


def test_a_quiniela_in_draw_order_is_not_sorted_and_that_is_fine():
    numbers = {"quiniela": ["999", "001", "500"], "tombola": []}
    assert shapes.problems(QN, date(2016, 6, 1), QN_SHAPE, numbers, {}) == []


def test_a_range_that_is_not_low_high_fails_loudly(tmp_path):
    path = tmp_path / "game_rules.csv"
    path.write_text("game,rule,value,valid_from,valid_to\n5_de_oro,rango_numeros,1 a 44,,\n")
    with pytest.raises(ValueError, match="'1 a 44' is not a range"):
        shapes.load_ranges(path, {(ORO, "rango_numeros")})
