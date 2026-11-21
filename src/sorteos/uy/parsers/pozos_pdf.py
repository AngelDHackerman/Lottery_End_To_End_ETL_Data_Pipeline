"""The 5 de Oro pozos PDF: the only source of the draw number (DESIGN.md, C11).

A JasperReports report (``reporteInformacionDePozos``), one page, issued on the day of the draw
before it (between 13:09 and 21:39 in local bronze, usually ~21:08 for the 22:00 draw) and
linked from ver_resultados since 2016-06-01. Its text, as pdfplumber extracts it, has had the
same seven lines in all 1,025 PDFs of local bronze:

    5 DE ORO CON REVANCHA
    Sorteo del día: 01/06/2016 1847 Emisión: 01/06/2016 21:11:21
    INFORMACIÓN DE POZOS
    MONTO PARA EL POZO DE ORO: $ 44.756.498,51
    MONTO PARA EL POZO DE PLATA: $ 546.709,80
    MONTO PARA EL POZO REVANCHA: $ 9.349.763,50
    01/06/2016 21:11:21 Página 1

The amounts are in the Uruguayan style, the same as the extract's (D6). Silver takes only the
draw number from here; the pools are the pools announced before the draw, returned so they
can be compared, and they differ from ver_resultados by cents in 4 of 3,075 (UY-024).

The number is returned as published. Whether it follows the sequence of draws is decided when
silver is written (``draw_number_out_of_sequence``, UY-025), because it takes the neighbours.
"""

from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

import pdfplumber

from sorteos.core.money import parse_amount
from sorteos.uy.parsers.common import BlockError, epoch_version
from sorteos.uy.sources import CONFIG, ORO

SOURCE = "pozos_5_de_oro"
(_SPEC,) = (s for s in CONFIG.games[ORO].sources if s.name == SOURCE)
FIRST_DAY = min(e.valid_from for e in _SPEC.parser_epochs)  # the first PDF linked: 2016-06-01

_DATE = r"(\d{2})/(\d{2})/(\d{4})"
_STAMP = r"(\d{2})/(\d{2})/(\d{4}) (\d{2}):(\d{2}):(\d{2})"
_TEXT = re.compile(
    "5 DE ORO CON REVANCHA\n"
    rf"Sorteo del día: {_DATE} (\d+) Emisión: {_STAMP}\n"
    "INFORMACIÓN DE POZOS\n"
    r"MONTO PARA EL POZO DE ORO: (\$ ?[\d.,]*)\n"
    r"MONTO PARA EL POZO DE PLATA: (\$ ?[\d.,]*)\n"
    r"MONTO PARA EL POZO REVANCHA: (\$ ?[\d.,]*)\n"
    rf"{_STAMP} Página 1"
)
PRIZES = ("oro", "plata", "revancha")


@dataclass(frozen=True)
class ParsedPozos:
    draw_date: date
    draw_number: int
    issued_local: datetime  # Montevideo wall-clock time, as printed
    pools: tuple[tuple[str, Decimal | None], ...]  # (prize, amount) in page order


def parser_version(day: date) -> int:
    version = epoch_version(_SPEC.parser_epochs, day)
    if version is None:
        raise BlockError(f"no parser epoch of {SOURCE} covers {day}")
    return version


def parse(content: bytes, day: date) -> ParsedPozos:
    parser_version(day)
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            if len(pdf.pages) != 1:
                raise BlockError(f"{len(pdf.pages)} pages, expected 1")
            text = pdf.pages[0].extract_text() or ""
    except BlockError:
        raise
    except Exception as exc:  # pdfminer raises its own types for a broken file
        raise BlockError(f"not a readable PDF ({type(exc).__name__})") from exc
    return parse_text(text, day)


def parse_text(text: str, day: date) -> ParsedPozos:
    match = _TEXT.fullmatch(text.strip())
    if not match:
        raise BlockError("the text is not the pozos report's seven lines")
    groups = match.groups()
    dd, mm, yyyy = (int(g) for g in groups[0:3])
    if (yyyy, mm, dd) != (day.year, day.month, day.day):
        raise BlockError(f"report for {yyyy}-{mm:02d}-{dd:02d}")
    number = int(groups[3])
    i_dd, i_mm, i_yyyy, hh, mi, ss = (int(g) for g in groups[4:10])
    try:
        issued = datetime(i_yyyy, i_mm, i_dd, hh, mi, ss)
        pools = tuple(
            (prize, parse_amount(amount, _SPEC.money_style))
            for prize, amount in zip(PRIZES, groups[10:13], strict=True)
        )
    except ValueError as exc:  # AmountError is one too
        raise BlockError(str(exc)) from exc
    return ParsedPozos(day, number, issued, pools)
