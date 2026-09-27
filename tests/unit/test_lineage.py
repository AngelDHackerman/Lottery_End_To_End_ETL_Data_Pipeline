"""Tests for the Silver lineage contract (PR-045.1, fault F).

Lineage is metadata *about* a write, so most of what can go wrong with it is silent: a
column that is always populated proves nothing, a column that is populated with the wrong
thing is worse than an empty one, and a column nothing can read is not lineage at all.
These tests are shaped around those three failures rather than around the happy path.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd
import pytest

from loteria.common.lineage import (
    INGESTED_AT,
    LINEAGE_COLUMNS,
    PARSER_VERSION,
    PARSER_VERSION_COLUMN,
    RUN_ID,
    SOURCE_KEY,
    run_id_from_env,
    utc_now,
)

REPO = Path(__file__).parents[2]


class TestRunIdIsNullRatherThanInvented:
    """The single most important decision in this module.

    A substituted value ("manual", the hostname, a uuid) would make `run_id` always
    populated and therefore useless: the data-quality gate's only contribution here is
    `run_id is not null` on lineage-era rows, which is the one check in the project that can
    notice something wrote Silver outside the pipeline. Filling the gap answers the question
    the gate is asking.
    """

    def test_a_correlation_id_is_used_verbatim(self):
        assert run_id_from_env({"CORRELATION_ID": "exec-abc"}) == "exec-abc"

    def test_an_absent_correlation_id_is_none(self):
        assert run_id_from_env({}) is None

    def test_an_empty_or_whitespace_correlation_id_is_none(self):
        """Step Functions cannot produce these, but a hand-run `--CORRELATION_ID=` can, and
        an empty string would satisfy a not-null expectation while carrying no provenance."""
        assert run_id_from_env({"CORRELATION_ID": ""}) is None
        assert run_id_from_env({"CORRELATION_ID": "   "}) is None

    def test_surrounding_whitespace_is_stripped(self):
        assert run_id_from_env({"CORRELATION_ID": " exec-abc \n"}) == "exec-abc"


class TestIngestedAtIsNaiveUtc:
    def test_it_is_naive(self):
        """Deliberate: Athena's `timestamp` has no zone, and the two business date columns
        already in Silver are naive. A single tz-aware column would be the odd one out for
        the crawler and for Athena both."""
        assert utc_now().tzinfo is None

    def test_it_is_actually_utc_and_not_local_time(self):
        """The failure this guards is a naive LOCAL timestamp, which looks identical in the
        data and is wrong by the machine's offset. The test box runs at UTC-03."""
        assert (
            abs(
                (utc_now() - dt.datetime.now(dt.timezone.utc).replace(tzinfo=None))  # noqa: UP017
                .total_seconds()
            )
            < 5
        )


class TestTheGlueRuntimeCeiling:
    def test_lineage_avoids_the_datetime_utc_alias(self):
        """`dt.UTC` is Python 3.11+. This module ships in the Glue zip and the transform job
        is a Python Shell job pinned to 3.9, so the alias ruff keeps suggesting would pass
        CI, import fine on the 3.12 Lambda, and raise AttributeError in the weekly run."""
        source = (REPO / "src/loteria/common/lineage.py").read_text(encoding="utf-8")
        code = "\n".join(line for line in source.splitlines() if not line.strip().startswith("#"))
        assert "dt.UTC" not in code
        assert "datetime.UTC" not in code


class TestGoldCannotInheritSilverColumnsByAccident:
    """The roadmap's "watch out", pinned as a test.

    New Silver columns must not leak into Gold. They cannot today because every gold CTAS
    names its columns — but that is a property of seven files that nobody is currently
    required to preserve. This is what keeps the *next* Silver column safe.
    """

    @pytest.mark.parametrize(
        "sql_file", sorted((REPO / "sql/gold").glob("*.sql")), ids=lambda p: p.name
    )
    def test_no_gold_ctas_uses_select_star(self, sql_file):
        import re

        sql = sql_file.read_text(encoding="utf-8")
        # `COUNT(*)` and `count(*)` are fine and common; a bare `SELECT *` (or `SELECT a.*`)
        # is what would pull lineage columns into a gold table unannounced.
        offenders = re.findall(r"SELECT\s+(?:[A-Za-z_][A-Za-z0-9_]*\.)?\*", sql, re.IGNORECASE)
        assert not offenders, f"{sql_file.name} uses SELECT *: {offenders}"

    def test_there_are_gold_files_to_check(self):
        """Guards the parametrize above: an empty glob would make every case vanish and the
        class would read as green while checking nothing."""
        assert len(list((REPO / "sql/gold").glob("*.sql"))) == 7


class TestTheContractItself:
    def test_column_order_is_stable(self):
        """Parquet column order follows this tuple, so a reordering shows up as a schema
        diff in the catalog. Pinned so that it is a decision rather than an accident."""
        assert LINEAGE_COLUMNS == (RUN_ID, INGESTED_AT, SOURCE_KEY, PARSER_VERSION_COLUMN)

    def test_parser_version_is_an_int_so_a_floor_comparison_works(self):
        """The suites gate on `parser_version >= N`. A string version would compare
        lexicographically and quietly mis-sort at 10."""
        assert isinstance(PARSER_VERSION, int)

    def test_a_frame_stamped_with_the_contract_round_trips_through_parquet(self, tmp_path):
        """pandas will accept anything; Parquet is the actual contract, and `None` in an
        object column is the case that could land as the string "None"."""
        df = pd.DataFrame({"numero_sorteo": [1]})
        df[RUN_ID] = None
        df[INGESTED_AT] = utc_now()
        df[SOURCE_KEY] = "raw/year=2026/sorteo=1/f.txt"
        df[PARSER_VERSION_COLUMN] = PARSER_VERSION

        path = tmp_path / "s.parquet"
        df.to_parquet(path, index=False)
        back = pd.read_parquet(path)

        assert back[RUN_ID].isna().all()
        assert back[SOURCE_KEY].iloc[0] == "raw/year=2026/sorteo=1/f.txt"
        assert int(back[PARSER_VERSION_COLUMN].iloc[0]) == PARSER_VERSION
