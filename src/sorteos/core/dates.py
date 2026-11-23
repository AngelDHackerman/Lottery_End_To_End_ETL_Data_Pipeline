"""Day-month-year dates typed by hand, read without ever correcting a digit (DESIGN.md, D14 rule 6).

Accepted: ``/``, ``-``, ``.`` or spaces between the parts, one or several in a row
(``12 / /02 / 2025``); the compact ``ddmmyyyy``; a year of 2 or 4 digits (2 means 20yy).
Anything else is ``None``: ``30 / 09 / 203`` and ``30 / 07 / 25007`` are not dates, and
turning them into 2023 or 2007 would be a guess (owner, 2026-10-21).
"""

from __future__ import annotations

import re
from datetime import date

_COMPACT = re.compile(r"(\d{2})(\d{2})(\d{4})")
_PARTS = re.compile(r"(\d{1,2})[\s/.\-]+(\d{1,2})[\s/.\-]+(\d{2}|\d{4})")


def parse_dmy(text: str) -> date | None:
    value = text.strip()
    match = _COMPACT.fullmatch(value) or _PARTS.fullmatch(value)
    if not match:
        return None
    day, month, year = (int(g) for g in match.groups())
    if len(match.group(3)) == 2:
        year += 2000
    try:
        return date(year, month, day)
    except ValueError:  # 31/02 is not a date either
        return None
