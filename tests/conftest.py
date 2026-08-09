"""Shared pytest fixtures and collection rules.

Two jobs:

1. Expose the anonymized sorteo fixtures (see ``tests/fixtures/sorteos/README.md``).
2. Keep the ``integration`` marker opt-in, so ``pytest`` with no arguments never reaches out
   to the network.
"""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
SORTEOS = FIXTURES / "sorteos"


# --------------------------------------------------------------------------------------
# awsglue stub (PR-030)
# --------------------------------------------------------------------------------------
# loteria.transformer.transformer does `from awsglue.utils import getResolvedOptions` at
# MODULE scope. awsglue ships only inside the Glue runtime — it is not on PyPI and cannot be
# installed — so importing the transformer anywhere else is an ImportError before a single
# line of the transform runs.
#
# Registering a stub in sys.modules is what makes the module importable under test. It is
# deliberately minimal: only `main()` calls getResolvedOptions, and `main()` is the Glue
# entry point, not the unit under test. Any test that reached it would get the TypeError
# below rather than a silently empty options dict.
if "awsglue" not in sys.modules:
    _awsglue = types.ModuleType("awsglue")
    _utils = types.ModuleType("awsglue.utils")

    def _get_resolved_options(argv, options):  # pragma: no cover - guard, not behaviour
        raise TypeError(
            "getResolvedOptions is stubbed in tests. transform() is the unit under test; "
            "main() is the Glue entry point and needs the real Glue runtime."
        )

    _utils.getResolvedOptions = _get_resolved_options
    _awsglue.utils = _utils
    sys.modules["awsglue"] = _awsglue
    sys.modules["awsglue.utils"] = _utils


# --------------------------------------------------------------------------------------
# Collection: integration tests are opt-in
# --------------------------------------------------------------------------------------
def pytest_collection_modifyitems(config, items):
    """Skip ``@pytest.mark.integration`` unless ``RUN_LIVE_SCRAPER=1``.

    Deselecting rather than erroring matters for the coverage gate: a skipped test still
    counts as collected, so `make test` reports honestly instead of looking like the suite
    shrank.
    """
    if os.environ.get("RUN_LIVE_SCRAPER") == "1":
        return

    skip = pytest.mark.skip(reason="live external call; set RUN_LIVE_SCRAPER=1 to run")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip)


# --------------------------------------------------------------------------------------
# Fixture files
# --------------------------------------------------------------------------------------
# Captured from raw/ and scrubbed by scripts/anonymize_fixture.py. The counts are asserted
# in the tests, so a regenerated fixture that silently changes shape fails loudly instead of
# quietly weakening the suite.
SORTEO_FILES = {
    "ordinario_3046": SORTEOS / "ordinario_3046.txt",
    "ordinario_3132": SORTEOS / "ordinario_3132.txt",
    "extraordinario_413": SORTEOS / "extraordinario_413.txt",
}


@pytest.fixture(scope="session")
def sorteo_files() -> dict[str, Path]:
    """All three fixture paths, keyed by short name."""
    return dict(SORTEO_FILES)


@pytest.fixture(scope="session")
def ordinario_lines() -> list[str]:
    """Lines of the 2024 ordinario sorteo 3046 — the default 'normal file' fixture."""
    return SORTEO_FILES["ordinario_3046"].read_text(encoding="utf-8").splitlines()


@pytest.fixture(scope="session")
def extraordinario_lines() -> list[str]:
    """Lines of the 2026 extraordinario 413.

    Worth having as a separate fixture: extraordinarios use their own numbering sequence
    (411, 412, 413 — not the 3xxx ordinario series) and, in this capture, contain zero
    ``NO VENDIDO`` lines. Both are easy assumptions to bake in accidentally.
    """
    return SORTEO_FILES["extraordinario_413"].read_text(encoding="utf-8").splitlines()
