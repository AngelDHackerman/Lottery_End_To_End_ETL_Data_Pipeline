"""UY-026: the GX suites, their frames, the committed JSON and the gate's exit code.

Every expectation is shown to fail on a frame that breaks it, and to be the only one that
fails: an expectation that never goes red protects nothing (verify a check by removing it).
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest

from sorteos.core import dq as core
from sorteos.core import silver
from sorteos.uy import dq_flags as dq
from sorteos.uy.dq import frames, runner, suites

REPO = Path(__file__).resolve().parents[3]
LINEAGE = {
    "ingested_at": datetime(2026, 10, 28, 12, 0, 0),
    "run_id": "run-1",
    "source_key": "country=uy/source=resultados/year=2016/resultados_2016-06-01.html",
    "source_sha256": "0" * 64,
    "parser_version": "resultados:1",
}
WED, SAT = date(2016, 6, 1), date(2016, 6, 4)
QUINIELA = [f"{n:03d}" for n in (512, 7, 999, 100, 345, 678, 12, 901, 250, 333,
                                 444, 555, 666, 777, 888, 121, 232, 343, 454, 565)]  # fmt: skip
TOMBOLA = [f"{n:02d}" for n in range(0, 100, 5)]
ORO, EXTRA, REVANCHA = ["03", "11", "20", "33", "44"], ["07"], ["01", "09", "15", "28", "40"]


def _key(game, day):
    return {"country": "uy", "operator": "dnlq", "game": game, "draw_date": day}


def draw(game, day, **changes):
    row = {
        **_key(game, day),
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


def numbers(game, day, ball, values):
    return [
        {
            **_key(game, day),
            "ball_type": ball,
            "position": i,
            "is_draw_order": ball == "quiniela",
            "number": value,
            "is_replacement": None,
            **LINEAGE,
        }
        for i, value in enumerate(values, 1)
    ]


def prize(name, status="no_winners", coupons=0, amount="44756498.51"):
    return {
        **_key("5_de_oro", WED),
        "prize": name,
        "pool_amount": Decimal(amount),
        "currency": "UYU",
        "winners_status": status,
        "winning_coupons": coupons,
        "dq_flags": [],
        **LINEAGE,
    }


def gap(game, previous, expected, next_draw, status, event, expected_from="announcement"):
    return {
        "country": "uy",
        "operator": "dnlq",
        "game": game,
        "previous_draw_date": previous,
        "expected_date": expected,
        "expected_from": expected_from,
        "window_end": expected + timedelta(days=3),
        "next_draw_date": next_draw,
        "status": status,
        "calendar_event_date": event,
        **LINEAGE,
    }


#: The 2019 strike, explained, and a Nocturna that has not come back, open.
GAPS = [
    gap(
        "5_de_oro",
        date(2019, 9, 22),
        date(2019, 9, 25),
        date(2019, 10, 1),
        "explained",
        date(2019, 9, 25),
    ),
    gap("quiniela_nocturna", SAT, date(2016, 6, 6), None, "open", None, "calendar"),
]


def clean_silver(root: Path) -> Path:
    """A small silver every suite passes: the three games, written by the real writer."""
    times = {
        "started_local": datetime(2016, 6, 1, 15, 0),
        "first_ball_local": datetime(2016, 6, 1, 15, 2),
        "ended_local": datetime(2016, 6, 1, 15, 20),
    }
    draws = [
        draw("5_de_oro", WED, draw_number=1847),
        draw("quiniela_vespertina", WED, **times),
        draw("quiniela_nocturna", SAT, **{k: v.replace(day=4) for k, v in times.items()}),
    ]
    nums = numbers("5_de_oro", WED, "oro", ORO) + numbers("5_de_oro", WED, "extra", EXTRA)
    nums += numbers("5_de_oro", WED, "revancha", REVANCHA)
    for game, day in (("quiniela_vespertina", WED), ("quiniela_nocturna", SAT)):
        nums += numbers(game, day, "quiniela", QUINIELA) + numbers(game, day, "tombola", TOMBOLA)
    prizes = [prize("oro"), prize("plata", "winners", 2), prize("revancha", "unknown", None)]
    for table, rows in (
        (silver.DRAWS, draws),
        (silver.DRAW_NUMBERS, nums),
        (silver.PRIZES, prizes),
    ):
        silver.write(root, table, rows, country="uy", year=2016, flags=dq.CATALOG)
    silver.write(root, silver.DRAW_GAPS, GAPS, country="uy")
    return root


@pytest.fixture(scope="module")
def root(tmp_path_factory):
    return clean_silver(tmp_path_factory.mktemp("silver"))


@pytest.fixture
def tables(root):
    tables = (silver.DRAWS, silver.DRAW_NUMBERS, silver.PRIZES, silver.DRAW_GAPS)
    return {t.name: core.load(root, t) for t in tables}


def failed(tables) -> set[tuple[str, str, str | None]]:
    report = runner.check(*(tables[n] for n in ("draws", "draw_numbers", "prizes", "draw_gaps")))
    return {(r.suite, o.expectation, o.column) for r in report.results for o in r.failures}


def where(frame, **match):
    mask = pd.Series(True, index=frame.index)
    for column, value in match.items():
        mask &= frame[column].astype(str) == str(value)
    assert mask.any(), match
    return mask


# --- The clean silver -----------------------------------------------------------------------


def test_the_clean_silver_passes_every_suite(root):
    report = runner.run(root)
    assert report.success, report.text()
    assert [r.suite for r in report.results] == list(suites.BUILDERS)
    assert report.text().endswith("PASSED")


def test_load_gives_partition_columns_their_schema_types(tables):
    draws = tables["draws"]
    assert draws["country"].tolist() == ["uy"] * 3
    assert not any(draws[c].dtype.name == "category" for c in ("country", "game"))
    assert draws["year"].dtype.name == "int32"


def test_a_table_without_files_is_refused(tmp_path):
    with pytest.raises(core.TableEmpty, match="draws"):
        core.load(tmp_path, silver.DRAWS)


# --- Each expectation goes red on its own -----------------------------------------------------


def _drop(frame, **match):
    return frame[~where(frame, **match)].reset_index(drop=True)


def _set(frame, column, value, **match):
    frame = frame.copy()
    frame[column] = frame[column].astype(object)
    mask = where(frame, **match)
    # A list is one value (dq_flags), not one value per row.
    frame.loc[mask, column] = pd.Series([value] * mask.sum(), index=frame.index[mask])
    return frame


def _twice(frame, **match):
    return pd.concat([frame, frame[where(frame, **match)]], ignore_index=True)


V, N, G5 = "quiniela_vespertina", "quiniela_nocturna", "5_de_oro"
D, DN, P = suites.DRAWS, suites.DRAW_NUMBERS, suites.PRIZES
S, F, GG = suites.DRAW_SHAPES, suites.DQ_FLAGS, suites.DRAW_GAPS
BETWEEN, IN_SET, NULL = (
    "expect_column_values_to_be_between",
    "expect_column_values_to_be_in_set",
    "expect_column_values_to_be_null",
)
NOT_NULL = "expect_column_values_to_not_be_null"


def _moved(t, game, day):
    """Move one draw, its numbers and its prizes to ``day``."""
    for name in ("draws", "draw_numbers", "prizes"):
        mask = t[name]["game"] == game
        t[name] = t[name].copy()
        t[name]["draw_date"] = t[name]["draw_date"].astype(object)
        t[name].loc[mask, "draw_date"] = day
    return t


CASES = {
    "duplicated gap": (
        lambda t: t | {"draw_gaps": _twice(t["draw_gaps"], game=G5)},
        {(GG, "expect_compound_columns_to_be_unique", "country,operator,game,previous_draw_date")},
    ),
    "a gap of a game outside v1": (
        lambda t: t | {"draw_gaps": _set(t["draw_gaps"], "game", "kini", game=N)},
        {(GG, IN_SET, "game")},
    ),
    "a gap neither explained nor open": (
        lambda t: t | {"draw_gaps": _set(t["draw_gaps"], "status", "pending", game=N)},
        {(GG, IN_SET, "status")},
    ),
    "an explained gap without its event": (
        lambda t: t | {"draw_gaps": _set(t["draw_gaps"], "calendar_event_date", None, game=G5)},
        {(GG, NOT_NULL, "calendar_event_date")},
    ),
    "an open gap with an event": (
        lambda t: t
        | {"draw_gaps": _set(t["draw_gaps"], "calendar_event_date", date(2016, 6, 6), game=N)},
        {(GG, NULL, "calendar_event_date")},
    ),
    "an expected date from nowhere": (
        lambda t: t | {"draw_gaps": _set(t["draw_gaps"], "expected_from", "guess", game=N)},
        {(GG, IN_SET, "expected_from")},
    ),
    "a window of 4 days": (
        lambda t: t | {"draw_gaps": _set(t["draw_gaps"], "window_end", date(2016, 6, 10), game=N)},
        {(GG, IN_SET, "window_days")},
    ),
    "a gap expected before the draw that set it": (
        lambda t: t
        | {
            "draw_gaps": _set(
                _set(t["draw_gaps"], "expected_date", date(2016, 6, 3), game=N),
                "window_end",
                date(2016, 6, 6),
                game=N,
            )
        },
        {(GG, IN_SET, "expected_after_previous")},
    ),
    "a gap whose draw came inside the window": (
        lambda t: t
        | {"draw_gaps": _set(t["draw_gaps"], "next_draw_date", date(2019, 9, 27), game=G5)},
        {(GG, IN_SET, "next_after_window")},
    ),
    "a gap without run_id": (
        lambda t: t | {"draw_gaps": _set(t["draw_gaps"], "run_id", None, game=G5)},
        {(GG, NOT_NULL, "run_id")},
    ),
    "duplicated draw": (
        lambda t: t | {"draws": _twice(t["draws"], game=V)},
        {(D, "expect_compound_columns_to_be_unique", "country,operator,game,draw_date")},
    ),
    "a game outside v1": (
        lambda t: t | {"draws": _set(t["draws"], "game", "kini", game=V)},
        {(D, IN_SET, "game"), (DN, IN_SET, "draw_key")},
    ),
    "a Nocturna on Sunday": (
        lambda t: _moved(t, N, date(2016, 6, 5)),
        {(D, "expect_column_values_to_not_be_in_set", "weekday")},
    ),
    "a Vespertina on Saturday": (
        lambda t: _moved(t, V, SAT),
        {(D, "expect_column_values_to_not_be_in_set", "weekday")},
    ),
    "a Quiniela with a draw number": (
        lambda t: t | {"draws": _set(t["draws"], "draw_number", 5, game=V)},
        {(D, NULL, "draw_number")},
    ),
    "a repeated draw number": (
        lambda t: _number_twice(t, []),
        {(D, "expect_column_values_to_be_unique", "draw_number")},
    ),
    "a draw number before the first pozos PDF": (
        lambda t: _moved(t, G5, date(2016, 5, 29)),
        {(D, NULL, "draw_number")},
    ),
    "a 5 de Oro with times": (
        lambda t: t | {"draws": _set(t["draws"], "ended_local", datetime(2016, 6, 1), game=G5)},
        {(D, NULL, "ended_local")},
    ),
    "a draw without run_id": (
        lambda t: t | {"draws": _set(t["draws"], "run_id", None, game=G5)},
        {(D, NOT_NULL, "run_id")},
    ),
    "a ball type of another game": (
        lambda t: t
        | {
            "draw_numbers": _set(
                t["draw_numbers"], "ball_type", "oro", game=V, ball_type="tombola", position=20
            )
        },  # fmt: skip
        {(DN, IN_SET, "ball_type"), (S, IN_SET, "count")},
    ),
    "a Quiniela number with 2 digits": (
        lambda t: t
        | {
            "draw_numbers": _set(
                t["draw_numbers"], "number", "12", game=V, ball_type="quiniela", position=1
            )
        },  # fmt: skip
        {(DN, "expect_column_values_to_match_regex", "number")},
    ),
    "a 5 de Oro number with 3 digits": (
        lambda t: t
        | {
            "draw_numbers": _set(t["draw_numbers"], "number", "044", ball_type="extra")
        },  # fmt: skip
        {(DN, "expect_column_values_to_match_regex", "number")},
    ),
    "a 5 de Oro number out of its epoch's range": (
        lambda t: t
        | {
            "draw_numbers": _set(
                t["draw_numbers"], "number", "49", ball_type="revancha", position=5
            )
        },  # fmt: skip
        {(DN, BETWEEN, "value")},
    ),
    "45 before 2014-03-19": (
        lambda t: _old_epoch_45(t),
        {(DN, BETWEEN, "value")},
    ),
    "numbers without their draw": (
        lambda t: t | {"draws": _drop(t["draws"], game=N)},
        {(DN, IN_SET, "draw_key")},
    ),
    "a prize without its draw": (
        lambda t: t | {"draws": _drop(t["draws"], game=G5)},
        {(DN, IN_SET, "draw_key"), (P, IN_SET, "draw_key")},
    ),
    "19 Quiniela numbers": (
        lambda t: t
        | {
            "draw_numbers": _drop(t["draw_numbers"], game=N, ball_type="quiniela", position=20)
        },  # fmt: skip
        {(S, BETWEEN, "count")},
    ),
    "a gap in the positions": (
        lambda t: t
        | {
            "draw_numbers": _set(
                t["draw_numbers"], "position", 21, game=N, ball_type="quiniela", position=20
            )
        },  # fmt: skip
        {(S, IN_SET, "positions_ok")},
    ),
    "an incomplete Tómbola": (
        lambda t: t
        | {
            "draw_numbers": _drop(t["draw_numbers"], game=N, ball_type="tombola", position=20)
        },  # fmt: skip
        {(S, IN_SET, "count")},
    ),
    "a Tómbola out of order": (
        lambda t: t
        | {
            "draw_numbers": _set(
                t["draw_numbers"], "number", "99", game=N, ball_type="tombola", position=1
            )
        },  # fmt: skip
        {(S, IN_SET, "ascending")},
    ),
    "a repeated Tómbola number after 2006": (
        lambda t: t
        | {
            "draw_numbers": _set(
                t["draw_numbers"], "number", "00", game=N, ball_type="tombola", position=2
            )
        },  # fmt: skip
        {(S, BETWEEN, "repeats")},
    ),
    "a missing extra": (
        lambda t: t | {"draw_numbers": _drop(t["draw_numbers"], ball_type="extra")},
        {(S, BETWEEN, "count")},
    ),
    "6 de Oro": (
        lambda t: t
        | {
            "draw_numbers": pd.concat(
                [
                    t["draw_numbers"],
                    t["draw_numbers"][where(t["draw_numbers"], ball_type="oro", position=5)].assign(
                        position=6
                    ),
                ],
                ignore_index=True,
            )
        },  # fmt: skip
        {(S, BETWEEN, "count")},
    ),
    "a missing Revancha number": (
        lambda t: t
        | {"draw_numbers": _drop(t["draw_numbers"], ball_type="revancha", position=5)},  # fmt: skip
        {(S, BETWEEN, "count")},
    ),
    "the extra among the 5 de Oro": (
        lambda t: t
        | {"draw_numbers": _set(t["draw_numbers"], "number", "33", ball_type="extra")},  # fmt: skip
        {(S, BETWEEN, "clashes")},
    ),
    "a currency that is not UYU": (
        lambda t: t | {"prizes": _set(t["prizes"], "currency", "USD", prize="oro")},
        {(P, IN_SET, "currency")},
    ),
    "a negative amount": (
        lambda t: t | {"prizes": _set(t["prizes"], "pool_amount", Decimal("-1.00"), prize="oro")},
        {(P, BETWEEN, "pool_amount")},
    ),
    "an unknown winners status": (
        lambda t: t | {"prizes": _set(t["prizes"], "winners_status", "maybe", prize="oro")},
        {(P, IN_SET, "winners_status")},
    ),
    "no_winners with coupons": (
        lambda t: t | {"prizes": _set(t["prizes"], "winning_coupons", 3, prize="oro")},
        {(P, BETWEEN, "winning_coupons")},
    ),
    "winners with 0 coupons": (
        lambda t: t | {"prizes": _set(t["prizes"], "winning_coupons", 0, prize="plata")},
        {(P, BETWEEN, "winning_coupons")},
    ),
    "unknown with a count": (
        lambda t: t | {"prizes": _set(t["prizes"], "winning_coupons", 1, prize="revancha")},
        {(P, NULL, "winning_coupons")},
    ),
    "winners without a count": (
        lambda t: t | {"prizes": _set(t["prizes"], "winning_coupons", None, prize="plata")},
        {(P, NOT_NULL, "winning_coupons")},
    ),
    "a flag outside the catalog": (
        lambda t: t | {"draws": _set(t["draws"], "dq_flags", ["made_up"], game=V)},
        {(F, IN_SET, "flag")},
    ),
    "a flag on the wrong table": (
        lambda t: t
        | {
            "prizes": _set(t["prizes"], "dq_flags", [dq.TOMBOLA_REPEATED_NUMBER], prize="oro")
        },  # fmt: skip
        {(F, IN_SET, "flag")},
    ),
    "empty tables": (
        lambda t: {name: frame.iloc[0:0] for name, frame in t.items()},
        {(s, "expect_table_row_count_to_be_between", None) for s in (D, DN, S, P)},
    ),
}


def _number_twice(t, flags):
    """A second 5 de Oro, the Sunday after, with the same draw number and these flags."""
    out = dict(t)
    for name in ("draws", "draw_numbers"):
        second = t[name][t[name]["game"] == G5].assign(draw_date=date(2016, 6, 5))
        if name == "draws":
            second["dq_flags"] = [flags] * len(second)
        out[name] = pd.concat([t[name], second], ignore_index=True)
    return out


def _old_epoch_45(t):
    """A 45 in a 5 de Oro of 2014-03-16, the last day of 01-44."""
    t = t | {
        "draws": _set(t["draws"], "draw_number", None, game=G5),
        "draw_numbers": _set(t["draw_numbers"], "number", "45", ball_type="revancha", position=5),
    }
    return _moved(t, G5, date(2014, 3, 16))


@pytest.mark.parametrize("case", CASES)
def test_each_expectation_fails_alone_on_what_it_guards(tables, case):
    mutate, expected = CASES[case]
    assert failed(mutate(tables)) == expected


def test_a_number_out_of_sequence_may_repeat(tables):
    assert failed(_number_twice(tables, [dq.DRAW_NUMBER_OUT_OF_SEQUENCE])) == set()


def test_a_quiniela_without_tombola_is_allowed(tables):
    # Owner, UY-022: the Vespertina of 2006-08-31 was published without its Tómbola.
    t = tables | {"draw_numbers": _drop(tables["draw_numbers"], game=V, ball_type="tombola")}
    assert failed(t) == set()


def test_tombola_repeats_are_allowed_in_2006(tables):
    t = _moved(tables, N, date(2006, 9, 2))
    t["draw_numbers"] = _set(t["draw_numbers"], "number", "00", game=N, ball_type="tombola",
                             position=2)  # fmt: skip
    assert failed(t) == set()


def test_the_catalog_flags_pass(tables):
    t = tables | {
        "draws": _set(tables["draws"], "dq_flags", [dq.DRAW_NUMBER_INFERRED], game=G5),
        "prizes": _set(tables["prizes"], "dq_flags", [dq.POZO_PLATA_EQUALS_ORO], prize="plata"),
    }
    assert failed(t) == set()


# --- Frames ---------------------------------------------------------------------------------


def test_shapes_has_one_row_per_draw_and_expected_ball_type(tables):
    draws = frames.draws(tables["draws"])
    out = frames.shapes(draws, frames.draw_numbers(tables["draw_numbers"]))
    assert len(out) == 2 + 2 + 3
    oro = out[out["ball_type"] == "oro"].iloc[0]
    assert (oro["count"], oro["positions_ok"], oro["ascending"], oro["repeats"]) == (
        5,
        True,
        True,
        0,
    )


def test_flags_unroll_one_row_per_flag(tables):
    draws = _set(tables["draws"], "dq_flags", [dq.TIMING_OUT_OF_ORDER, dq.NEXT_DRAW_UNPARSED],
                 game=N)  # fmt: skip
    out = frames.flags(frames.draws(draws), frames.prizes(tables["prizes"]))
    assert out["flag"].tolist() == ["draws.timing_out_of_order", "draws.next_draw_unparsed"]
    assert out["draw_date"].tolist() == ["2016-06-04"] * 2


def test_the_draw_key_spells_the_whole_key(tables):
    assert "uy|dnlq|5_de_oro|2016-06-01" in frames.draw_key(frames.draws(tables["draws"])).tolist()


# --- Suites and their JSON ------------------------------------------------------------------


@pytest.mark.parametrize("name", suites.BUILDERS)
def test_committed_json_matches_the_code(name):
    path = REPO / "qa" / "uy" / "expectations" / f"{name}.json"
    assert path.read_text(encoding="utf-8") == core.suite_json(
        suites.BUILDERS[name]()
    ), f"{path.name} is out of date: run `make uy-dq-sync` and commit the diff"


def test_no_committed_suite_is_left_without_a_builder():
    committed = {p.stem for p in (REPO / "qa" / "uy" / "expectations").glob("*.json")}
    assert committed == set(suites.BUILDERS)


def test_committed_json_carries_no_random_ids():
    for name in suites.BUILDERS:
        assert '"id"' not in core.suite_json(suites.BUILDERS[name]())


def test_the_flags_suite_is_the_catalog():
    (expectation,) = suites.build_dq_flags().expectations
    assert set(expectation.value_set) == {f"{t}.{f}" for f, t in dq.CATALOG.items()}


def test_the_ranges_come_from_game_rules_when_the_gate_runs():
    extra = suites.run_time(["uy|dnlq|5_de_oro|2016-06-01"])
    ranges = [e for e in extra[DN] if e.column == "value"]
    assert [(e.min_value, e.max_value) for e in ranges] == [(1, 44), (1, 48)]
    assert [e.value_set for e in extra[DN] if e.column == "draw_key"] == [
        ["uy|dnlq|5_de_oro|2016-06-01"]
    ]
    assert extra[P][0] is not extra[DN][-1]


# --- The report and the command -------------------------------------------------------------


def test_an_empty_report_is_not_a_success():
    assert not core.Report([]).success


def test_the_report_names_suite_expectation_column_and_sample(tables):
    t = tables | {"prizes": _set(tables["prizes"], "currency", "USD", prize="oro")}
    report = runner.check(t["draws"], t["draw_numbers"], t["prizes"], t["draw_gaps"])
    assert "  - expect_column_values_to_be_in_set on currency: 1 unexpected, e.g. ['USD']" in (
        report.text()
    )
    as_dict = report.to_dict()
    assert as_dict["success"] is False
    json.dumps(as_dict)  # the JSON report has nothing GX-specific left in it


def test_an_expectation_that_errors_is_a_failure():
    import great_expectations as gx
    from great_expectations import expectations as gxe

    suite = gx.ExpectationSuite(name="t", expectations=[gxe.ExpectColumnValuesToBeNull(column="x")])
    (outcome,) = core.validate(suite, pd.DataFrame({"y": [1]})).outcomes
    assert not outcome.success and outcome.error


def test_an_error_is_found_at_the_top_or_under_a_metric():
    assert core._error(None) is None
    assert core._error({"raised_exception": True, "exception_message": "boom"}) == "boom"
    assert core._error({"raised_exception": True}) == "raised"
    assert core._error({"metric-id": {"exception_message": "inner"}}) == "inner"
    assert core._error({"raised_exception": False, "exception_message": None}) is None


def test_samples_are_plain_values():
    import numpy as np

    assert core._plain([np.int64(3), date(2016, 6, 1), "a", None]) == [3, "2016-06-01", "a", None]


def test_main_exits_0_on_green_and_writes_the_json_report(root, tmp_path, capsys):
    out = tmp_path / "dq.json"
    assert runner.main(["--silver", str(root), "--json-report", str(out)]) == runner.EXIT_OK
    assert json.loads(out.read_text())["success"] is True
    assert capsys.readouterr().out.endswith("PASSED\n")


def test_main_exits_1_when_a_suite_fails(tmp_path):
    root = clean_silver(tmp_path)
    silver.write(root, silver.PRIZES, [prize("oro"), prize("plata", "winners", 0)],
                 country="uy", year=2016, flags=dq.CATALOG)  # fmt: skip
    assert runner.main(["--silver", str(root)]) == runner.EXIT_FAILED


def test_main_exits_2_without_silver(tmp_path, capsys):
    assert runner.main(["--silver", str(tmp_path)]) == runner.EXIT_NO_DATA
    assert "no Parquet files" in capsys.readouterr().err


def test_sync_writes_one_file_per_suite(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "SUITES_DIR", tmp_path / "out")
    assert runner.main(["--sync-suites"]) == runner.EXIT_OK
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == sorted(
        f"{name}.json" for name in suites.BUILDERS
    )
