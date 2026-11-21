"""Amounts as published, read with the style of the source that published them (DESIGN.md, D6).

``365,323`` or ``1.234`` mean different things depending on where they came from, so the style
is never guessed from the value: it comes from the source's ``money_style`` in the YAML.

- ``us``: ``9,999,999.99`` (``ver_resultados``);
- ``uy``: ``9.999.999,99`` (the 5 de Oro extract).

Always two decimals and grouped thousands, matched in full. Empty (a bare ``$``) is ``None``,
never 0, and so is ``0,00``, the extract's empty-template marker. Anything else raises, and
the draw goes to quarantine.
"""

from __future__ import annotations

import re
from decimal import Decimal

_PATTERNS = {
    "us": re.compile(r"\d{1,3}(?:,\d{3})*\.\d{2}"),
    "uy": re.compile(r"\d{1,3}(?:\.\d{3})*,\d{2}"),
}
_EMPTY_TEMPLATE = {"uy": "0,00"}


class AmountError(ValueError):
    pass


def parse_amount(text: str, style: str) -> Decimal | None:
    if style not in _PATTERNS:
        raise ValueError(f"unknown money style {style!r}")
    value = "".join(text.replace("$", "").split())
    if not value or value == _EMPTY_TEMPLATE.get(style):
        return None
    if not _PATTERNS[style].fullmatch(value):
        raise AmountError(f"{text!r} is not a {style} amount")
    if style == "us":
        return Decimal(value.replace(",", ""))
    return Decimal(value.replace(".", "").replace(",", "."))
