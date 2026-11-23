"""Amounts by source style (D6) and hand-typed day-month-year dates (D14, rule 6)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from sorteos.core.dates import parse_dmy
from sorteos.core.money import AmountError, parse_amount


@pytest.mark.parametrize(
    ("text", "style", "expected"),
    [
        ("35,409,043.86", "us", Decimal("35409043.86")),
        ("$ 110,629,426.70", "us", Decimal("110629426.70")),
        ("491,571.60", "us", Decimal("491571.60")),
        ("0.00", "us", Decimal("0.00")),
        ("110.629.426,70", "uy", Decimal("110629426.70")),
        ("999.999,99", "uy", Decimal("999999.99")),
        ("$", "us", None),  # the bare "$" of ver_resultados 2006-08-20
        ("  ", "us", None),
        ("0,00", "uy", None),  # the extract's empty template, never 0
    ],
)
def test_amounts_are_read_with_the_style_of_their_source(text, style, expected):
    assert parse_amount(text, style) == expected


@pytest.mark.parametrize(
    ("text", "style"),
    [
        ("365,323", "us"),  # no decimals: ambiguous, so refused
        ("1.234", "us"),
        ("110.629.426,70", "us"),  # the other style
        ("35,409,043.86", "uy"),
        ("1,23.45", "us"),
        ("1234,567.00", "us"),  # a group of four
        ("35,409,043.8", "us"),
        ("-5.00", "us"),
    ],
)
def test_an_amount_that_does_not_match_its_style_raises(text, style):
    with pytest.raises(AmountError):
        parse_amount(text, style)


def test_an_unknown_style_is_a_programming_error():
    with pytest.raises(ValueError, match="unknown money style"):
        parse_amount("1.00", "eu")


# Every shape of "Próximo" seen in local bronze, 2006–2026 (UY-022 properties run).
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("18 / 11 / 2006", date(2006, 11, 18)),
        ("31/10/2006", date(2006, 10, 31)),
        ("21 / 01 /2009", date(2009, 1, 21)),
        ("28 /01 / 2008", date(2008, 1, 28)),
        ("1 / 12 / 2006", date(2006, 12, 1)),
        ("28 / 2 / 2012", date(2012, 2, 28)),
        ("5/7/2022", date(2022, 7, 5)),
        ("06092006", date(2006, 9, 6)),  # compact ddmmyyyy
        ("06 / 06 / 07", date(2007, 6, 6)),  # two-digit year
        ("11/ 5 / 22", date(2022, 5, 11)),
        ("12 / /02 / 2025", date(2025, 2, 12)),  # a repeated separator
        ("17/ /09 / 2025", date(2025, 9, 17)),
        ("22 - 05 - 2018", date(2018, 5, 22)),
        ("27 / 05 2024", date(2024, 5, 27)),  # a missing slash, spaces still separate
        ("25 04 / 2020", date(2020, 4, 25)),
        ("01.02.2020", date(2020, 2, 1)),
    ],
)
def test_hand_typed_dates_are_read(text, expected):
    assert parse_dmy(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        "30 / 09 / 203",  # never "corrected" to 2023 (owner, 2026-10-21)
        "30 / 07 / 25007",  # nor to 2007
        "31 / 02 / 2020",  # not a day of the calendar
        "",
        "1 / 2",
        "0609206",
        "Domingo 3 de Setiembre de 2006",
    ],
)
def test_what_is_not_a_date_is_none(text):
    assert parse_dmy(text) is None
