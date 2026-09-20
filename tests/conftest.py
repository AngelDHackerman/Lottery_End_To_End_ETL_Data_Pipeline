"""Shared pytest fixtures and collection rules.

Three jobs:

1. Pin a fake AWS environment, so the suite behaves the same on a laptop and in CI.
2. Expose the anonymized sorteo fixtures (see ``tests/fixtures/sorteos/README.md``).
3. Keep the ``integration`` marker opt-in, so ``pytest`` with no arguments never reaches out
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
# A fake AWS environment (PR-035)
# --------------------------------------------------------------------------------------
# Several modules build their boto3 clients at MODULE scope — `purge_and_load.py:49` is the
# clearest — and boto3 needs a region before it will build one. On a developer box the
# region arrives from ~/.aws/config or an exported AWS_PROFILE, so the tests pass; a runner
# with no AWS configuration at all raises `NoRegionError` at import, before a single
# assertion. That is exactly how PR-035 first went red in CI while green on the machine that
# wrote it.
#
# Set rather than `setdefault` on purpose. Deferring to whatever the developer happens to
# have exported is what let the difference hide in the first place, and forcing the values
# has a second benefit: no test can reach real AWS by accident, even if a `mock_aws` is ever
# forgotten. Every AWS-touching test here runs under moto, which ignores the values and only
# requires that they exist.
#
# The opt-in live test (RUN_LIVE_SCRAPER=1) is unaffected: it talks to loteria.org.gt
# through scrape.do and reads SCRAPE_DO_TOKEN from the environment, not from AWS.
os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
os.environ["AWS_ACCESS_KEY_ID"] = "testing"
os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"  # nosec B105 - a moto placeholder
os.environ["AWS_SESSION_TOKEN"] = "testing"  # nosec B105 - a moto placeholder
os.environ["AWS_SECURITY_TOKEN"] = "testing"  # nosec B105 - a moto placeholder
os.environ.pop("AWS_PROFILE", None)


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

    Skipping rather than deselecting matters for the coverage gate: a skipped test still
    counts as collected, so `make test` reports honestly instead of looking like the suite
    shrank.

    ⚠️ Use ``get_closest_marker``, NOT ``"integration" in item.keywords``. ``item.keywords``
    also contains the test's **path components**, so the keywords check matches every test
    living under ``tests/integration/`` whether or not it carries the marker. That bug was
    invisible while the directory was empty (PR-029) and only surfaced in PR-031, where it
    silently skipped the one offline test in that folder — the guard that keeps the canary's
    selectors in sync with the scraper. A guard that never runs is worse than no guard.
    """
    if os.environ.get("RUN_LIVE_SCRAPER") == "1":
        return

    skip = pytest.mark.skip(reason="live external call; set RUN_LIVE_SCRAPER=1 to run")
    for item in items:
        if item.get_closest_marker("integration") is not None:
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
