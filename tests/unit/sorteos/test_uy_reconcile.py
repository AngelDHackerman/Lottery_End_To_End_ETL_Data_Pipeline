"""UY-030.1: ``uy-reconcile`` over silver written for the test, with the real reference CSVs."""

from __future__ import annotations

import json
from collections import Counter
from datetime import date, datetime

import pytest

from sorteos.core import reconcile as rc
from sorteos.core import silver as core_silver
from sorteos.uy import dq_flags as dq
from sorteos.uy import reconcile, silver
from sorteos.uy.sources import COUNTRY, ORO, QN

RUN = silver.Run(datetime(2026, 11, 1, 12, 0), "uy-test")
TODAY = date(2019, 10, 9)


def d(day: str) -> date:
    return date.fromisoformat(day)


def draw(day, announced, number=None, flags=(), game=ORO):
    return {
        "country": COUNTRY,
        "operator": "dnlq",
        "game": game,
        "draw_date": d(day),
        "draw_number": number,
        "next_draw_text": None,
        "next_draw_date": d(announced) if announced else None,
        "started_local": None,
        "first_ball_local": None,
        "ended_local": None,
        "timezone": "America/Montevideo",
        "cross_source_check": "match",
        "dq_flags": list(flags),
        "ingested_at": RUN.ingested_at,
        "run_id": RUN.run_id,
        "source_key": f"resultados_{day}.html",
        "source_sha256": "a" * 64,
        "parser_version": "resultados:1",
    }


# The 5 de Oro around the 2019 AFAL strike, as silver has it. The 22nd announced the 25th,
# and the strike (calendar_events 2019-09-25 to 27) kept it away until Tuesday 1-Oct. Then
# 2-Oct was moved to Friday the 4th, and the Sunday 6th to Monday the 7th, both announced.
STRIKE = [
    ("2019-09-15", "2019-09-18", 2079),
    ("2019-09-18", "2019-09-22", 2080),
    ("2019-09-22", "2019-09-25", 2081),
    ("2019-10-01", "2019-10-04", 2082),
    ("2019-10-04", "2019-10-07", 2083),
    ("2019-10-07", None, 2084),
]


def write(root, rows, gaps=True, today=TODAY):
    for year in sorted({r["draw_date"].year for r in rows}):
        core_silver.write(
            root,
            core_silver.DRAWS,
            [r for r in rows if r["draw_date"].year == year],
            country=COUNTRY,
            year=year,
            flags=dq.CATALOG,
        )
    silver.write_reference(root, RUN)
    if gaps:
        silver.write_gaps(root, RUN, today)


def strike(**changes):
    rows = [draw(day, announced, number) for day, announced, number in STRIKE]
    for i, flags in changes.items():
        rows[int(i[1:])]["dq_flags"] = flags
    return rows


def test_the_strike_is_one_explained_gap_and_every_day_has_its_reason(tmp_path):
    write(tmp_path, strike())
    report = reconcile.collect(tmp_path, TODAY)

    assert report.problems == []
    (game,) = report.games
    assert [(x.day.isoformat(), x.kind) for x in game.days if x.kind != rc.ON_CALENDAR] == [
        ("2019-09-25", rc.GAP_EXPLAINED),
        ("2019-09-29", rc.GAP_EXPLAINED),
        ("2019-10-01", rc.OFF_CALENDAR_OTHER),
        ("2019-10-02", rc.SKIPPED),
        ("2019-10-04", rc.OFF_CALENDAR_ANNOUNCED),
        ("2019-10-06", rc.SKIPPED),
        ("2019-10-07", rc.OFF_CALENDAR_ANNOUNCED),
    ]
    assert game.totals["calendar"] == game.weekdays_counted == 7
    (gap,) = report.gaps
    assert (gap["expected_date"], gap["status"]) == (d("2019-09-25"), "explained")
    (series,) = report.series
    assert (series.numbered, series.steps, series.breaks) == (6, Counter({1: 5}), [])

    text = reconcile.format_report(report)
    assert "**Result: ok**" in text
    assert "| 5_de_oro | 2019-09-15 | 2019-10-07 | 6 | 7 |" in text
    assert "- 2019-10-01 (Tue): off_calendar_other" in text
    # Only the 5 de Oro's event: the same day suspended the Quinielas, in a row of their own.
    assert "| explained | 2019-09-25: traslado (paro parcial de AFAL (13:30 a 23:59)) |" in text
    assert "6 numbered draws (6 read, 0 inferred), 0 without a number" in text
    assert "Steps between consecutive draws: 5× +1" in text
    assert "0 rows against 6 draws in silver (0.00 %)." in text


def test_a_break_in_the_draw_number_passes_only_on_a_flagged_draw(tmp_path):
    rows = strike(r4=[dq.DRAW_NUMBER_OUT_OF_SEQUENCE])
    rows[4]["draw_number"] = rows[5]["draw_number"] = 2084  # 2017-08-16 repeated its number
    write(tmp_path, rows)
    assert reconcile.collect(tmp_path, TODAY).problems == [
        f"5_de_oro: 2084 on 2019-10-04 then 2084 on 2019-10-07, not flagged "
        f"{dq.DRAW_NUMBER_OUT_OF_SEQUENCE}"
    ]
    rows[5]["dq_flags"] = [dq.DRAW_NUMBER_OUT_OF_SEQUENCE]
    write(tmp_path, rows)
    report = reconcile.collect(tmp_path, TODAY)
    assert report.problems == []
    assert "Steps between consecutive draws: 1× +0, 3× +1, 1× +2" in reconcile.format_report(report)


def test_a_draw_without_a_number_after_the_first_numbered_one_is_a_problem(tmp_path):
    rows = strike()
    rows[0]["draw_number"] = None  # before the first numbered draw: not counted
    rows[3]["draw_number"] = None
    write(tmp_path, rows)
    report = reconcile.collect(tmp_path, TODAY)
    assert report.problems == [
        "5_de_oro: no draw number on 2019-10-01",
        # The number on each side of the hole is right, so the step is +2, and unflagged.
        f"5_de_oro: 2081 on 2019-09-22 then 2083 on 2019-10-04, not flagged "
        f"{dq.DRAW_NUMBER_OUT_OF_SEQUENCE}",
    ]
    assert report.series[0].first["draw_date"] == d("2019-09-18")


def test_an_open_gap_fails_and_a_stale_draw_gaps_says_how_to_fix_it(tmp_path):
    # A Wednesday missing with no calendar_events row: March 2018 has none.
    rows = [
        draw("2018-03-04", "2018-03-07"),
        draw("2018-03-11", "2018-03-14"),
        draw("2018-03-14", None),
    ]
    write(tmp_path, rows, gaps=False)  # silver from before the gap was found
    report = reconcile.collect(tmp_path, date(2018, 3, 15))
    assert report.problems == [
        "5_de_oro: 1 calendar days in open gaps",
        "draw_gaps is stale: only recomputed: "
        "('5_de_oro', datetime.date(2018, 3, 4), datetime.date(2018, 3, 7), 'open', None)",
    ]
    text = reconcile.format_report(report)
    assert "**Result: FAILED**" in text
    assert "No gaps." in text  # what silver has
    assert "Differs from a recomputation today (run `make uy-silver`):" in text
    assert "- 2018-03-07 (Wed): gap_open" in text


def test_an_open_gap_in_silver_is_listed_without_an_event(tmp_path):
    rows = [
        draw("2018-03-04", "2018-03-07"),
        draw("2018-03-11", "2018-03-14"),
        draw("2018-03-14", None, game=QN),  # a game without a draw number
    ]
    write(tmp_path, rows, today=date(2018, 3, 15))
    report = reconcile.collect(tmp_path, date(2018, 3, 15))
    assert report.problems == ["5_de_oro: 1 calendar days in open gaps"]
    assert report.series == []
    text = reconcile.format_report(report)
    assert "| 5_de_oro | 2018-03-04 | 2018-03-07 | announcement | 2018-03-11 | open | — |" in text
    assert "No game has a draw number." in text


def test_quarantine_fails_and_reports_its_rate(tmp_path):
    write(tmp_path, strike())
    quarantined = {
        "country": COUNTRY,
        "operator": "dnlq",
        "source": "resultados",
        "draw_date": d("2019-09-29"),
        "game": None,  # the whole page
        "reason": "bad page",
        "ingested_at": RUN.ingested_at,
        "run_id": RUN.run_id,
        "source_key": "resultados_2019-09-29.html",
        "source_sha256": "b" * 64,
        "parser_version": "resultados:1",
    }
    core_silver.write(tmp_path, core_silver.QUARANTINE, [quarantined], country=COUNTRY, year=2019)
    report = reconcile.collect(tmp_path, TODAY)
    assert report.problems == ["quarantine: 1 rows"]
    text = reconcile.format_report(report)
    assert "1 rows against 6 draws in silver (14.29 %)." in text
    assert "- 1 resultados: bad page" in text


def test_a_report_without_gaps_or_numbers_says_so():
    text = reconcile.format_report(reconcile.Reconciliation(TODAY))
    assert "No gaps." in text and "No game has a draw number." in text


def test_empty_silver_reports_nothing_and_passes(tmp_path):
    report = reconcile.collect(tmp_path, TODAY)
    assert report.problems == []
    assert "Silver is empty." in reconcile.format_report(report)


def test_main_prints_the_report_writes_the_months_and_sets_the_exit_code(
    tmp_path, capsys, monkeypatch
):
    monkeypatch.setattr(reconcile.backfill, "today_in_uruguay", lambda: TODAY)
    write(tmp_path / "s", strike())
    out = tmp_path / "months.json"
    assert reconcile.main(["--silver", str(tmp_path / "s"), "--json-report", str(out)]) == 0
    assert capsys.readouterr().out.startswith("# UY reconciliation — 2019-10-09\n")
    months = json.loads(out.read_text())
    assert months[ORO]["2019-09"]["gap_explained"] == 2
    assert months[ORO]["2019-10"]["draws"] == 3

    monkeypatch.setattr(reconcile.backfill, "today_in_uruguay", lambda: date(2019, 10, 20))
    assert reconcile.main(["--silver", str(tmp_path / "s")]) == 1  # the 7th's window closed


@pytest.mark.parametrize("missing", [1, 2])
def test_calendar_weekdays_that_do_not_add_up_are_a_problem(missing):
    days = [rc.Day(d("2019-09-15"), rc.ON_CALENDAR)]
    game = reconcile.Game(ORO, days, rc.month_counts(days), weekdays_counted=1 + missing)
    report = reconcile.Reconciliation(TODAY, games=[game])
    assert report.problems == [
        f"5_de_oro: 1 calendar weekdays accounted for, {1 + missing} counted from the dates"
    ]
