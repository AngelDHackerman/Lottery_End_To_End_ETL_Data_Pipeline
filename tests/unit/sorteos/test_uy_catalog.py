"""The UY silver tables in the Glue catalog (UY-044.1): scripts/uy_catalog_schema.py and the JSON
Terraform reads (terraform/uy/silver_tables.json, catalog.tf).

What is pinned here is what `terraform plan` cannot know: that the declared tables are the
ones the silver writer writes, column by column, and that the projected partitions are the
paths it writes them to.
"""

from __future__ import annotations

import importlib.util
import json
import re
from datetime import date
from pathlib import Path

import pyarrow as pa
import pytest

from sorteos.core import silver

REPO = Path(__file__).parents[3]
JSON = REPO / "terraform" / "uy" / "silver_tables.json"
CATALOG_TF = REPO / "terraform" / "uy" / "catalog.tf"


def _script():
    path = REPO / "scripts" / "uy_catalog_schema.py"
    spec = importlib.util.spec_from_file_location("uy_catalog_schema", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def script():
    return _script()


@pytest.fixture(scope="module")
def tables() -> dict:
    return json.loads(JSON.read_text("utf-8"))["tables"]


def test_the_committed_json_is_what_the_script_writes(script):
    assert (
        JSON.read_text("utf-8") == script.render()
    ), "terraform/uy/silver_tables.json is stale: run `make uy-catalog-sync` and commit it"


def test_check_mode_tells_a_stale_file_from_a_current_one(script, tmp_path, monkeypatch, capsys):
    assert script.main(["--check"]) == 0
    stale = tmp_path / "silver_tables.json"
    stale.write_text(script.render().replace('"int"', '"bigint"', 1), "utf-8")
    monkeypatch.setattr(script, "OUT", stale)
    monkeypatch.setattr(script, "ROOT", tmp_path)
    assert script.main(["--check"]) == 1
    assert "stale" in capsys.readouterr().out
    assert script.main([]) == 0
    assert stale.read_text("utf-8") == script.render()


def test_every_silver_table_is_declared(tables):
    assert set(tables) == set(silver.TABLES)


@pytest.mark.parametrize("name", sorted(silver.TABLES))
def test_columns_are_the_files_columns_in_order(tables, name):
    spec = silver.TABLES[name]
    declared = [c["name"] for c in tables[name]["columns"]]
    assert declared == spec.file_schema.names
    # A partition column declared as a column too would be read twice: Athena refuses it.
    assert not set(declared) & {k["name"] for k in tables[name]["partition_keys"]}


@pytest.mark.parametrize("name", sorted(silver.TABLES))
def test_partition_keys_are_the_path_the_writer_uses(tables, name):
    spec = silver.TABLES[name]
    expected = [*spec.partition, *(["year"] if spec.year_of else [])]
    keys = tables[name]["partition_keys"]
    assert [k["name"] for k in keys] == expected
    assert {k["name"]: k["type"] for k in keys}.get("year", "int") == "int"
    # Every partition key is projected, or Athena finds no partition at all.
    assert set(tables[name]["projection"]) == set(expected)


def test_types(script):
    assert script.glue_type(pa.string()) == "string"
    assert script.glue_type(pa.date32()) == "date"
    assert script.glue_type(pa.int32()) == "int"
    assert script.glue_type(pa.bool_()) == "boolean"
    assert script.glue_type(pa.timestamp("us")) == "timestamp"
    assert script.glue_type(pa.decimal128(18, 2)) == "decimal(18,2)"
    assert script.glue_type(pa.list_(pa.string())) == "array<string>"


@pytest.mark.parametrize(
    "kind", [pa.int64(), pa.null(), pa.timestamp("us", tz="UTC"), pa.float64(), pa.large_string()]
)
def test_a_type_without_a_mapping_is_an_error_never_a_guess(script, kind):
    # int64 and null are the two silent traps of core/silver.py's docstring.
    with pytest.raises(script.CatalogError):
        script.glue_type(kind)


def test_money_keeps_its_scale(tables):
    types = {c["name"]: c["type"] for c in tables["prizes"]["columns"]}
    assert types["pool_amount"] == "decimal(18,2)"  # D6
    assert types["dq_flags"] == "array<string>"


def test_games_come_from_the_game_yamls(script, tables):
    games = script.games()
    assert games == ["5_de_oro", "quiniela_nocturna", "quiniela_vespertina"]
    assert tables["draws"]["projection"]["game"] == {"type": "enum", "values": ",".join(games)}
    assert tables["draws"]["projection"]["country"] == {"type": "enum", "values": "uy"}


def test_the_projected_years_cover_history_and_do_not_run_out(script, tables):
    first, last = map(int, tables["draws"]["projection"]["year"]["range"].split(","))
    assert first == 2006  # site.yaml, history_starts
    # A year past the bound is written to S3 and invisible to Athena, with no error anywhere.
    # This fails two years early: raise LAST_YEAR in scripts/uy_catalog_schema.py.
    assert date.today().year <= last - 2, "raise LAST_YEAR in scripts/uy_catalog_schema.py"
    assert (first, last) == (script.FIRST_YEAR, script.LAST_YEAR)


def test_an_unknown_partition_column_is_an_error(script):
    with pytest.raises(script.CatalogError):
        script._projection("operator")


def test_terraform_reads_the_json_and_declares_no_crawler():
    text = CATALOG_TF.read_text("utf-8")
    assert 'file("${path.module}/silver_tables.json")' in text
    assert '"projection.enabled" = "true"' in text
    assert not re.search(r'resource\s+"aws_glue_crawler"', text)  # owner, UY-044 3a
    # The scan limit is set, and CTAS can still choose its location (UY-044.3).
    assert "bytes_scanned_cutoff_per_query" in text
    assert re.search(r"enforce_workgroup_configuration\s*=\s*false", text)
