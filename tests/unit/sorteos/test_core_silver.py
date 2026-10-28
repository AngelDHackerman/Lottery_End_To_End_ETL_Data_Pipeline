"""The silver contract: explicit types, the checks before a write and the per-year rewrite."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from sorteos.core import silver
from sorteos.uy import dq_flags

NOW = datetime(2026, 10, 28, 12, 0, 0)
REFERENCE = Path(silver.__file__).parents[1] / "uy" / "reference"
LINEAGE = {
    "ingested_at": NOW,
    "run_id": "run-1",
    "source_key": "country=uy/source=resultados/year=2016/resultados_2016-06-01.html",
    "source_sha256": "0" * 64,
    "parser_version": "resultados:1",
}


def draw(game="5_de_oro", day=date(2016, 6, 1), **changes):
    row = {
        "country": "uy",
        "operator": "dnlq",
        "game": game,
        "draw_date": day,
        "draw_number": None,
        "next_draw_text": None,
        "next_draw_date": None,
        "started_local": None,
        "first_ball_local": None,
        "ended_local": None,
        "timezone": "America/Montevideo",
        "cross_source_check": "match",
        "dq_flags": [],
        **LINEAGE,
    }
    return row | changes


def prize(name="oro", **changes):
    row = {
        "country": "uy",
        "operator": "dnlq",
        "game": "5_de_oro",
        "draw_date": date(2016, 6, 1),
        "prize": name,
        "pool_amount": Decimal("44756498.51"),
        "currency": "UYU",
        "winners_status": "no_winners",
        "winning_coupons": 0,
        "dq_flags": [],
        **LINEAGE,
    }
    return row | changes


def quarantined(game=None, source="resultados", **changes):
    row = {
        "country": "uy",
        "operator": "dnlq",
        "source": source,
        "draw_date": date(2016, 6, 1),
        "game": game,
        "reason": "no game blocks",
        **LINEAGE,
    }
    return row | changes


def write(root, table, rows, year=2016):
    return silver.write(root, table, rows, country="uy", year=year, flags=dq_flags.CATALOG)


# --- schemas -----------------------------------------------------------------------------


def test_every_table_has_lineage_and_no_null_or_int64_column():
    for table in silver.TABLES.values():
        names = table.schema.names
        assert names[-5:] == [f.name for f in silver.LINEAGE]
        assert set(table.key) <= set(names) and set(table.partition) <= set(names)
        for field in table.schema:
            assert not pa.types.is_null(field.type), (table.name, field.name)
            assert field.type != pa.int64(), (table.name, field.name)
        assert not set(table.partition) & set(table.file_schema.names)


def test_money_and_counts_have_the_catalog_types():
    assert silver.PRIZES.schema.field("pool_amount").type == pa.decimal128(18, 2)
    assert silver.PRIZES.schema.field("winning_coupons").type == pa.int32()
    assert silver.DRAWS.schema.field("draw_number").type == pa.int32()
    assert silver.DRAW_NUMBERS.schema.field("position").type == pa.int32()
    assert silver.DRAW_NUMBERS.schema.field("number").type == pa.string()  # keeps its zeros
    assert silver.DRAWS.schema.field("dq_flags").type == pa.list_(pa.string())
    assert silver.DRAWS.schema.field("ingested_at").type == pa.timestamp("us")  # no zone


def test_utc_now_is_naive():
    assert silver.utc_now().tzinfo is None


def test_parser_version_lists_each_source_in_order():
    versions = {"resultados": 1, "extracto_quiniela_nocturna": 1, "pozos_5_de_oro": 2}
    assert silver.parser_version(versions) == (
        "resultados:1;extracto_quiniela_nocturna:1;pozos_5_de_oro:2"
    )


@pytest.mark.parametrize("versions", [{}, {"": 1}, {"a:b": 1}, {"a;b": 1}, {"a": True}])
def test_parser_version_rejects_what_it_could_not_split_back(versions):
    with pytest.raises(silver.SilverError):
        silver.parser_version(versions)


# --- write -------------------------------------------------------------------------------


def test_write_puts_each_game_in_its_partition_with_the_declared_types(tmp_path):
    rows = [draw(), draw("quiniela_nocturna", started_local=datetime(2016, 6, 1, 21, 0))]
    written = write(tmp_path, silver.DRAWS, rows)
    assert written == [
        tmp_path / "draws/country=uy/game=5_de_oro/year=2016/part-0.parquet",
        tmp_path / "draws/country=uy/game=quiniela_nocturna/year=2016/part-0.parquet",
    ]
    schema = pq.read_schema(written[0])
    # draw_number is None in every row and is still an int32, never the Null type
    assert schema.field("draw_number").type == pa.int32()
    assert schema.field("next_draw_date").type == pa.date32()
    assert "country" not in schema.names and "game" not in schema.names
    assert not list(tmp_path.rglob("*.tmp"))


def test_the_folder_reads_back_with_its_partition_columns(tmp_path):
    write(tmp_path, silver.PRIZES, [prize("oro"), prize("plata", pool_amount=None)])
    frame = pd.read_parquet(tmp_path / "prizes")
    assert set(frame["country"]) == {"uy"} and set(frame["game"]) == {"5_de_oro"}
    assert list(frame["prize"]) == ["oro", "plata"]
    assert frame["pool_amount"].iloc[0] == Decimal("44756498.51")
    assert frame["pool_amount"].iloc[1] is None


def test_rows_are_sorted_by_key_and_flags_by_name(tmp_path):
    rows = [
        draw(day=date(2016, 6, 5)),
        draw(day=date(2016, 6, 1), dq_flags=["next_draw_unparsed", "draw_number_inferred"]),
    ]
    (path,) = write(tmp_path, silver.DRAWS, rows)
    table = pq.read_table(path)
    assert table.column("draw_date").to_pylist() == [date(2016, 6, 1), date(2016, 6, 5)]
    assert table.column("dq_flags").to_pylist()[0] == [
        "draw_number_inferred",
        "next_draw_unparsed",
    ]


def test_a_rewrite_replaces_the_year_and_drops_a_game_left_without_rows(tmp_path):
    write(tmp_path, silver.DRAWS, [draw(), draw("quiniela_nocturna")])
    write(tmp_path, silver.DRAWS, [draw(day=date(2017, 1, 1))], year=2017)
    write(tmp_path, silver.DRAWS, [draw(day=date(2016, 6, 5))])
    base = tmp_path / "draws/country=uy"
    assert sorted(p.relative_to(base).as_posix() for p in base.rglob("*.parquet")) == [
        "game=5_de_oro/year=2016/part-0.parquet",
        "game=5_de_oro/year=2017/part-0.parquet",  # another year: untouched
    ]
    days = pq.read_table(base / "game=5_de_oro/year=2016/part-0.parquet").column("draw_date")
    assert days.to_pylist() == [date(2016, 6, 5)]


def test_writing_no_rows_empties_the_year(tmp_path):
    write(tmp_path, silver.DRAWS, [draw()])
    assert write(tmp_path, silver.DRAWS, []) == []
    assert not list((tmp_path / "draws").rglob("*.parquet"))
    assert write(tmp_path / "nothing-yet", silver.DRAWS, []) == []


def test_a_rejected_write_leaves_the_files_as_they_were(tmp_path):
    (path,) = write(tmp_path, silver.DRAWS, [draw()])
    before = path.read_bytes()
    with pytest.raises(silver.SilverError):
        write(tmp_path, silver.DRAWS, [draw(day=date(2016, 6, 5)), draw(dq_flags=["typo"])])
    assert path.read_bytes() == before


def test_quarantine_keeps_a_whole_day_without_game(tmp_path):
    rows = [quarantined(), quarantined("quiniela_nocturna", "extracto_quiniela_nocturna")]
    (path,) = write(tmp_path, silver.QUARANTINE, rows)
    assert path == tmp_path / "quarantine/country=uy/year=2016/part-0.parquet"
    games = pq.read_table(path).column("game").to_pylist()
    assert games == ["quiniela_nocturna", None]  # by source: the extract before resultados


# --- what a write refuses ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rows", "message"),
    [
        ([draw(typo=1)], r"unknown \['typo'\]"),
        ([{k: v for k, v in draw().items() if k != "timezone"}], r"missing \['timezone'\]"),
        ([draw(game=None)], r"\['game'\] cannot be null"),
        ([draw(dq_flags=None)], r"\['dq_flags'\] cannot be null"),
        ([draw(ingested_at=None)], r"\['ingested_at'\] cannot be null"),
        ([draw(country="gt")], "country 'gt'"),
        ([draw(day=date(2017, 1, 1))], "in year=2016"),
        ([draw(day="2016-06-01")], "in year=2016"),
        ([draw(dq_flags=["typo"])], "not in the dq_flags catalog"),
        ([draw(dq_flags=["pozo_plata_equals_oro"])], "belongs to prizes, not draws"),
        ([draw(dq_flags=["next_draw_unparsed"] * 2)], "repeats a flag"),
        ([draw(dq_flags="next_draw_unparsed")], "must be a list"),
        ([draw(), draw()], "is repeated"),
        ([draw(draw_number=2**31)], "draws"),
    ],
)
def test_a_row_that_cannot_be_written_as_it_is_is_refused(tmp_path, rows, message):
    with pytest.raises(silver.SilverError, match=message):
        write(tmp_path, silver.DRAWS, rows)
    assert not (tmp_path / "draws").exists()


def test_an_amount_with_three_decimals_is_refused_not_rounded(tmp_path):
    with pytest.raises(silver.SilverError, match="data loss"):
        write(tmp_path, silver.PRIZES, [prize(pool_amount=Decimal("1.005"))])


def test_the_year_must_match_how_the_table_is_partitioned(tmp_path):
    with pytest.raises(silver.SilverError, match="partitioned by draw_date"):
        write(tmp_path, silver.DRAWS, [draw()], year=None)
    with pytest.raises(silver.SilverError, match="partitioned by None"):
        write(tmp_path, silver.GAME_RULES, [], year=2016)


def test_without_a_catalog_no_flag_is_valid(tmp_path):
    with pytest.raises(silver.SilverError, match="not in the dq_flags catalog"):
        silver.write(
            tmp_path,
            silver.DRAWS,
            [draw(dq_flags=["next_draw_unparsed"])],
            **{
                "country": "uy",
                "year": 2016,
            },
        )


# --- reference tables --------------------------------------------------------------------


def reference(table, path):
    return silver.read_reference(
        path,
        table,
        country="uy",
        operator="dnlq",
        ingested_at=NOW,
        run_id=None,
        source_key=f"src/sorteos/uy/reference/{path.name}",
    )


def test_the_reference_csvs_go_to_parquet_untransformed(tmp_path):
    rules = reference(silver.GAME_RULES, REFERENCE / "game_rules.csv")
    events = reference(silver.CALENDAR_EVENTS, REFERENCE / "calendar_events.csv")
    assert rules[1]["rule"] == "rango_numeros"
    assert rules[1]["valid_from"] == date(2006, 8, 16)
    assert rules[1]["valid_to"] == date(2014, 3, 18)
    assert events[0]["event_date"] == date(2014, 9, 24)
    assert events[0]["moved_to"] == date(2014, 9, 25)
    assert events[0]["source_url"] is None  # an empty cell is null, never ""
    # UY-025.1 (owner, 1a): a day the source does not give stays null, never invented, and
    # the 2019 strike moved only the 5 de Oro, so each of those days is two rows.
    (revancha_2009,) = [r for r in rules if r["value"] == "$ 10" and r["valid_from"] is None]
    assert revancha_2009["valid_to"] == date(2012, 3, 3)
    strike = [(r["games"], r["moved_to"]) for r in events if r["event_date"] == date(2019, 9, 25)]
    assert strike == [
        ("5_de_oro", date(2019, 9, 26)),
        ("quiniela_nocturna,quiniela_vespertina", None),
    ]
    assert {r["parser_version"] for r in rules + events} == {None}
    assert len({r["source_sha256"] for r in rules}) == 1

    (path,) = silver.write(tmp_path, silver.GAME_RULES, rules, country="uy")
    assert path == tmp_path / "game_rules/country=uy/part-0.parquet"
    assert pq.read_table(path).num_rows == len(rules)
    assert pq.read_schema(path).field("valid_to").type == pa.date32()
    silver.write(tmp_path, silver.CALENDAR_EVENTS, events, country="uy")
    assert silver.write(tmp_path, silver.GAME_RULES, [], country="uy") == []
    assert not (tmp_path / "game_rules/country=uy").exists()


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("game,rule\n5_de_oro,x\n", "header"),
        (
            "game,rule,value,valid_from,valid_to,source,source_url,evidence\n"
            "5_de_oro,x,y,16/08/2006,,,,\n",
            "valid_from '16/08/2006'",
        ),
        (
            "game,rule,value,valid_from,valid_to,source,source_url,evidence\n5_de_oro,x\n",
            "not 8 cells",
        ),
        (
            "game,rule,value,valid_from,valid_to,source,source_url,evidence\n"
            "5_de_oro,x,y,,,,,,extra\n",
            "not 8 cells",
        ),
    ],
)
def test_a_reference_csv_that_does_not_fit_is_refused(tmp_path, text, message):
    path = tmp_path / "game_rules.csv"
    path.write_text(text)
    with pytest.raises(silver.SilverError, match=message):
        reference(silver.GAME_RULES, path)


def test_only_reference_tables_read_a_csv():
    with pytest.raises(silver.SilverError, match="not a reference table"):
        reference(silver.DRAWS, REFERENCE / "game_rules.csv")
