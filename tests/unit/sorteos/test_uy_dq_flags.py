"""D22: the code's catalog of dq_flags is the one DESIGN.md documents, flag by flag."""

from __future__ import annotations

import re
from pathlib import Path

from sorteos.core import silver
from sorteos.uy import dq_flags

DESIGN = Path(__file__).parents[3] / "docs" / "uruguay" / "DESIGN.md"
_ROW = re.compile(r"^\| `([a-z_]+)` \| `([a-z_]+)` \|", re.M)


def design_catalog() -> dict[str, str]:
    text = DESIGN.read_text(encoding="utf-8")
    section = text.split("### El catálogo (D22, P13)", 1)[1].split("\n### ", 1)[0]
    return dict(_ROW.findall(section))


def test_the_catalog_is_the_one_in_design():
    assert dq_flags.CATALOG == design_catalog()
    assert len(dq_flags.CATALOG) == 9  # P13's 7, plus UY-023's and UY-024's


def test_every_flag_goes_on_a_silver_table_that_has_dq_flags():
    for flag, table in dq_flags.CATALOG.items():
        assert "dq_flags" in silver.TABLES[table].schema.names, flag
