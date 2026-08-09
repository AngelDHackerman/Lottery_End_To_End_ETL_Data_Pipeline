"""Shared pytest fixtures and collection rules.

Two jobs:

1. Expose the anonymized sorteo fixtures (see ``tests/fixtures/sorteos/README.md``).
2. Keep the ``integration`` marker opt-in, so ``pytest`` with no arguments never reaches out
   to the network.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
SORTEOS = FIXTURES / "sorteos"


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
