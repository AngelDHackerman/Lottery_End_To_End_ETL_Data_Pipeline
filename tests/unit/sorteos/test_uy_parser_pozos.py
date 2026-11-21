"""The 5 de Oro pozos PDF: the draw number (C11), from real PDFs of 2016 and 2026."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from sorteos.uy.parsers import pozos_pdf
from sorteos.uy.parsers.common import BlockError

UY = Path(__file__).parents[2] / "fixtures" / "uy"
TEXT = (
    "5 DE ORO CON REVANCHA\n"
    "Sorteo del día: 01/06/2016 1847 Emisión: 01/06/2016 21:11:21\n"
    "INFORMACIÓN DE POZOS\n"
    "MONTO PARA EL POZO DE ORO: $ 44.756.498,51\n"
    "MONTO PARA EL POZO DE PLATA: $ 546.709,80\n"
    "MONTO PARA EL POZO REVANCHA: $ 9.349.763,50\n"
    "01/06/2016 21:11:21 Página 1"
)


@pytest.mark.parametrize(
    ("day", "number", "issued", "pools"),
    [
        (
            date(2016, 6, 1),  # the first PDF linked from ver_resultados
            1847,
            datetime(2016, 6, 1, 21, 11, 21),
            ("44756498.51", "546709.80", "9349763.50"),
        ),
        (
            date(2026, 10, 18),
            2920,
            datetime(2026, 10, 18, 21, 9, 2),
            ("27207734.26", "872082.00", "11552112.00"),
        ),
    ],
)
def test_a_real_pozos_pdf_gives_the_draw_number(day, number, issued, pools):
    parsed = pozos_pdf.parse((UY / f"pozos_5_de_oro_{day}.pdf").read_bytes(), day)
    assert (parsed.draw_date, parsed.draw_number, parsed.issued_local) == (day, number, issued)
    assert parsed.pools == tuple(
        zip(("oro", "plata", "revancha"), (Decimal(p) for p in pools), strict=True)
    )


def test_an_empty_amount_is_null_never_zero():
    parsed = pozos_pdf.parse_text(TEXT.replace("$ 546.709,80", "$"), date(2016, 6, 1))
    assert parsed.pools[1] == ("plata", None)


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        (TEXT.replace("01/06/2016 1847", "02/06/2016 1847"), "report for 2016-06-02"),
        (TEXT.replace(" 1847 ", " "), "seven lines"),
        (TEXT.replace("CON REVANCHA", "Y REVANCHA"), "seven lines"),
        (TEXT + "\nMONTO EXTRA: $ 1,00", "seven lines"),
        (TEXT.replace("44.756.498,51", "44,756,498.51"), "not a uy amount"),
        (TEXT.replace("21:11:21\nINFO", "25:11:21\nINFO"), "hour must be in"),
        ("", "seven lines"),
    ],
)
def test_text_that_is_not_the_report_fails(text, problem):
    with pytest.raises(BlockError, match=problem):
        pozos_pdf.parse_text(text, date(2016, 6, 1))


def test_bytes_that_are_not_a_pdf_fail():
    with pytest.raises(BlockError, match="not a readable PDF"):
        pozos_pdf.parse(b"<html>403 Forbidden</html>", date(2016, 6, 1))


def test_a_pdf_with_more_than_one_page_fails(monkeypatch):
    class TwoPages:
        pages = [object(), object()]

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(pozos_pdf.pdfplumber, "open", lambda _: TwoPages())
    with pytest.raises(BlockError, match="2 pages, expected 1"):
        pozos_pdf.parse(b"%PDF", date(2016, 6, 1))


def test_the_pdf_exists_only_from_2016_06_01():
    with pytest.raises(BlockError, match="no parser epoch"):
        pozos_pdf.parse(b"", date(2016, 5, 29))
    assert pozos_pdf.parser_version(date(2026, 10, 18)) == 1
