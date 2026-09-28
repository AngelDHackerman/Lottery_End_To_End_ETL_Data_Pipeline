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
    LINEAGE_GLUE_TYPES,
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


# ==========================================================================================
# PR-045.2 — the queryable half
# ==========================================================================================
class TestTheSilverTablesAreDeclaredNotCrawled:
    """The Silver table schemas moved from the crawlers to Terraform in PR-045.2.

    The crawlers could not evolve them (`UpdateBehavior = LOG`, `CRAWL_NEW_FOLDERS_ONLY`,
    partitions `InheritFromTable`), so PR-045.1's four columns existed in every new Parquet
    file and in no Athena query. These tests hold the two halves of the resulting contract
    together: `LINEAGE_GLUE_TYPES` here and `local.lineage_columns` in the `.tf`.
    """

    SILVER_TABLES = (
        'resource "aws_glue_catalog_table" "silver_sorteos"',
        'resource "aws_glue_catalog_table" "silver_premios"',
    )

    def _declared_lineage(self, tf_block):
        """The (name, type) pairs from `local.lineage_columns`, in file order."""
        import re

        block = tf_block("locals {")
        return re.findall(r'name\s*=\s*"(\w+)",\s*type\s*=\s*"(\w+)"', block)

    def test_terraform_declares_exactly_the_contract(self, tf_block):
        assert self._declared_lineage(tf_block) == [
            (name, LINEAGE_GLUE_TYPES[name]) for name in LINEAGE_COLUMNS
        ]

    @pytest.mark.parametrize("header", SILVER_TABLES)
    def test_both_tables_use_the_shared_lineage_block(self, tf_block, header):
        """Not "both declare four columns that look the same" — both must render from the
        one list, so the sorteos and premios lineage cannot drift apart by an edit that
        touches one table."""
        assert "for_each = local.lineage_columns" in tf_block(header)

    @pytest.mark.parametrize("header", SILVER_TABLES)
    def test_partition_keys_are_year_then_sorteo_and_are_not_columns(self, tf_block, header):
        """The live tables are partitioned this way and 118 registered partitions depend on
        it. Glue also rejects a table whose columns and partition keys overlap."""
        import re

        block = tf_block(header)
        partitions = re.findall(r'partition_keys\s*\{\s*name\s*=\s*"(\w+)"', block)
        columns = re.findall(r'columns\s*\{\s*name\s*=\s*"(\w+)"', block)

        assert partitions == ["year", "sorteo"]
        assert not set(partitions) & set(columns)

    def test_the_business_columns_are_exactly_what_the_crawler_left(self, tf_block):
        """The import is only safe if the declaration matches what is in the account. These
        are the columns `aws glue get-table` returned on 2026-09-28, spelled out rather than
        derived — deriving them from the transformer would make this agree with the code
        instead of with the catalog, and the catalog is what Athena reads."""
        import re

        sorteos = re.findall(r'columns\s*\{\s*name\s*=\s*"(\w+)"', tf_block(self.SILVER_TABLES[0]))
        premios = re.findall(r'columns\s*\{\s*name\s*=\s*"(\w+)"', tf_block(self.SILVER_TABLES[1]))

        assert sorteos == [
            "numero_sorteo",
            "tipo_sorteo",
            "fecha_sorteo",
            "fecha_caducidad",
            "primer_premio",
            "segundo_premio",
            "tercer_premio",
            "reintegro_primer_premio",
            "reintegro_segundo_premio",
            "reintegro_tercer_premio",
        ]
        assert premios == [
            "numero_sorteo",
            "numero_premiado",
            "letras",
            "monto",
            "vendedor",
            "ciudad",
            "departamento",
        ]

    @pytest.mark.parametrize("header", SILVER_TABLES)
    def test_the_location_is_the_silver_prefix_of_the_partitioned_bucket(self, tf_block, header):
        """A wrong location on an imported table does not fail the apply — it repoints the
        table Athena reads at a prefix that may not exist, and the first symptom is an empty
        result set."""
        dataset = "sorteos" if "sorteos" in header else "premios"
        assert f"/silver/{dataset}/" in tf_block(header)


class TestThePhysicalTypeMatchesTheDeclaredOne:
    """PR-045.2's other half: a declared schema is only as good as the bytes under it.

    Nothing checked these while the columns were invisible to Athena. Declaring them is what
    turns a type mismatch from a curiosity into an unreadable partition.
    """

    def test_parser_version_is_declared_bigint_because_pandas_writes_int64(self, tmp_path):
        """Athena widens INT to BIGINT and supports nothing in the other direction, so an
        `int` column over this file is the mismatch that cannot be read."""
        import pyarrow.parquet as pq

        df = pd.DataFrame({PARSER_VERSION_COLUMN: [PARSER_VERSION]})
        path = tmp_path / "pv.parquet"
        df.to_parquet(path, index=False)

        assert str(pq.read_schema(path).field(PARSER_VERSION_COLUMN).type) == "int64"
        assert LINEAGE_GLUE_TYPES[PARSER_VERSION_COLUMN] == "bigint"

    def test_an_all_none_column_is_written_as_parquet_null_not_as_a_string(self, tmp_path):
        """The defect itself, pinned. This is what the writers' casts exist to prevent: with
        no cast, `run_id` in a file written outside a pipeline run is physically
        `int32 (Null)`, and the catalog says `string`.

        It is asserted as the CURRENT pyarrow behaviour rather than as something desirable —
        if a future pyarrow starts inferring `string` here, this test failing is how we find
        out that the casts became belt and braces.
        """
        import pyarrow.parquet as pq

        df = pd.DataFrame({"a": [1]})
        df[RUN_ID] = None
        path = tmp_path / "raw.parquet"
        df.to_parquet(path, index=False)

        assert str(pq.read_schema(path).field(RUN_ID).type) == "null"

    def test_the_cast_the_writers_use_fixes_it(self, tmp_path):
        import pyarrow.parquet as pq
        import pyarrow.types as pat

        df = pd.DataFrame({"a": [1]})
        df[RUN_ID] = None
        df[RUN_ID] = df[RUN_ID].astype("string")
        path = tmp_path / "cast.parquet"
        df.to_parquet(path, index=False)

        field = pq.read_schema(path).field(RUN_ID)
        assert pat.is_string(field.type) or pat.is_large_string(field.type)


class TestTheLineageViews:
    """`sql/lineage/` is the queryable surface. These are shape checks, not a SQL engine —
    the SQL itself was validated against the live tables before it was committed (runbook
    §3), which is the part a unit test cannot do.
    """

    SQL_DIR = REPO / "sql/lineage"

    def test_there_are_exactly_two_view_files(self):
        """Guards the parametrised cases below: an empty glob would make them vanish and the
        class would read as green while checking nothing (the same guard PR-045.1 put on the
        gold files)."""
        assert sorted(p.name for p in self.SQL_DIR.glob("*.sql")) == [
            "01_silver_lineage.sql",
            "02_silver_lineage_runs.sql",
        ]

    @pytest.mark.parametrize(
        "sql_file", sorted((REPO / "sql/lineage").glob("*.sql")), ids=lambda p: p.name
    )
    def test_each_file_holds_exactly_one_statement(self, sql_file):
        """Athena's StartQueryExecution takes one statement. A second one does not run — it
        fails the whole execution, which for `sql/gold/` is handled by a Lambda that splits
        the file and for these is handled by not writing a second statement."""
        body = "\n".join(
            line
            for line in sql_file.read_text(encoding="utf-8").splitlines()
            if not line.strip().startswith("--")
        )
        assert body.count(";") == 0
        assert len([s for s in body.split("CREATE OR REPLACE VIEW") if s.strip()]) == 1

    def test_the_aggregate_view_reads_the_detail_view_not_the_tables(self):
        """The one structural decision in these files: two views over the same tables would
        be two definitions of lineage, free to drift while both look right."""
        runs = (self.SQL_DIR / "02_silver_lineage_runs.sql").read_text(encoding="utf-8")
        body = "\n".join(line for line in runs.splitlines() if not line.strip().startswith("--"))

        assert "FROM silver_lineage" in body
        assert "silver_sorteos_sorteos" not in body
        assert "silver_premios_premios" not in body

    def test_the_detail_view_selects_every_lineage_column(self):
        """A view that quietly dropped `source_key` would still answer two thirds of the
        question this sub-phase exists for, which is the kind of gap nobody notices."""
        detail = (self.SQL_DIR / "01_silver_lineage.sql").read_text(encoding="utf-8")
        body = "\n".join(line for line in detail.splitlines() if not line.strip().startswith("--"))

        for column in LINEAGE_COLUMNS:
            assert column in body, f"{column} is not in the detail view"

    def test_both_silver_datasets_are_in_the_detail_view(self):
        detail = (self.SQL_DIR / "01_silver_lineage.sql").read_text(encoding="utf-8")

        assert "silver_sorteos_sorteos" in detail
        assert "silver_premios_premios" in detail
        assert "UNION ALL" in detail

    def test_the_views_are_not_picked_up_by_the_gold_step_function(self):
        """Terraform globs `sql/gold/*.sql` into the gold Map state. If that glob were ever
        widened to `sql/`, these two files would be executed every Thursday as if they were
        CTAS — and 02 would fail the run."""
        orchestration = (REPO / "terraform/modules/orchestration/main.tf").read_text(
            encoding="utf-8"
        )

        assert 'fileset(local.gold_sql_dir, "*.sql")' in orchestration
        assert 'gold_sql_dir = "${path.module}/../../../sql/gold"' in orchestration
