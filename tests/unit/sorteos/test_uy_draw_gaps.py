"""UY-028.2: ``draw_gaps`` in silver — built from silver, skipped on quarantine, always rerun."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from test_uy_backfill import root_logger_restored  # noqa: F401 (a fixture)
from test_uy_silver import Lake

from sorteos.core import gaps
from sorteos.core import silver as core_silver
from sorteos.uy import build_silver, silver

RUN = silver.Run(datetime(2026, 10, 31, 12, 0), "uy-test")
DAY = date(2016, 7, 6)  # a fixture day with all three games
G5, QN = "5_de_oro", "quiniela_nocturna"


def draw(game, day, announced=None, key=None):
    return {
        "game": game,
        "draw_date": day,
        "next_draw_date": announced,
        "source_key": key or f"resultados_{day}.html",
        "source_sha256": "a" * 64,
        "parser_version": "resultados:1",
    }


def event(day, games):
    return {"event_date": day, "games": games}


# --- gap_rows: from rows, with the lineage of the draw that set the expectation ----------


def test_a_gap_carries_the_lineage_of_the_draw_whose_expectation_failed():
    draws = [
        draw(G5, date(2019, 10, 1)),  # any order: they are sorted per game
        draw(G5, date(2019, 9, 22), date(2019, 9, 25), key="the-22nd"),
    ]
    (row,) = silver.gap_rows(draws, [], RUN, today=date(2019, 10, 2))
    assert row == {
        "country": "uy",
        "operator": "dnlq",
        "game": G5,
        "previous_draw_date": date(2019, 9, 22),
        "expected_date": date(2019, 9, 25),
        "expected_from": gaps.ANNOUNCEMENT,
        "window_end": date(2019, 9, 28),
        "next_draw_date": date(2019, 10, 1),
        "status": gaps.OPEN,
        "calendar_event_date": None,
        "ingested_at": RUN.ingested_at,
        "run_id": "uy-test",
        "source_key": "the-22nd",
        "source_sha256": "a" * 64,
        "parser_version": "resultados:1",
    }


def test_an_event_explains_only_the_games_it_names():
    draws = [
        draw(G5, date(2019, 9, 22), date(2019, 9, 25)),
        draw(G5, date(2019, 10, 1)),
        draw(QN, date(2019, 9, 24), date(2019, 9, 25)),
        draw(QN, date(2019, 10, 1)),
    ]
    events = [event(date(2019, 9, 25), "5_de_oro, quiniela_vespertina")]  # spaces are fine
    rows = silver.gap_rows(draws, events, RUN, today=date(2019, 10, 2))
    assert [(r["game"], r["status"], r["calendar_event_date"]) for r in rows] == [
        (G5, gaps.EXPLAINED, date(2019, 9, 25)),
        (QN, gaps.OPEN, None),
    ]


def test_no_draws_no_gaps():
    assert silver.gap_rows([], [event(date(2019, 9, 25), G5)], RUN, date(2019, 10, 2)) == []


# --- core.silver.read: silver back as rows, partition columns typed ----------------------


def test_read_gives_rows_with_typed_partition_columns_and_no_year(tmp_path):
    assert core_silver.read(tmp_path, core_silver.DRAWS) == []
    lake = Lake(tmp_path)
    lake.fixture("resultados", DAY)
    build_silver.rebuild(lake.manifest, lake.bronze, tmp_path / "s", [2016], RUN)
    lake.manifest.close()

    rows = core_silver.read(tmp_path / "s", core_silver.DRAWS, ["game", "draw_date"])
    assert sorted(rows, key=lambda r: r["game"]) == [
        {"game": g, "draw_date": DAY} for g in (G5, QN, "quiniela_vespertina")
    ]
    full = core_silver.read(tmp_path / "s", core_silver.DRAWS)
    assert "year" not in full[0] and full[0]["country"] == "uy"


# --- detect_gaps: written whole, or not at all when silver has quarantine (owner, 3a) -----


def built(tmp_path):
    lake = Lake(tmp_path)
    lake.fixture("resultados", DAY)
    out = tmp_path / "s"
    build_silver.rebuild(lake.manifest, lake.bronze, out, [2016], RUN)
    return lake, out


def test_detect_gaps_writes_the_table_from_every_year_of_silver(tmp_path):
    lake, out = built(tmp_path)
    lake.manifest.close()
    # One draw per game and nothing after it: once their windows close, three open gaps.
    report = build_silver.detect_gaps(out, RUN, today=date(2016, 7, 31))
    assert sorted(r["game"] for r in report.rows) == [G5, QN, "quiniela_vespertina"]
    assert core_silver.read(out, core_silver.DRAW_GAPS) == sorted(
        report.rows, key=lambda r: r["game"]
    )
    text = build_silver.format_gaps(report)
    # The Quinielas' suspension of 2016-07-14 is a week after their window: it explains nothing.
    assert text.startswith("draw_gaps: 3 (0 explained, 3 open)")
    assert "open 5_de_oro expected " in text and "next draw none yet" in text

    # A window still open is not a gap yet, and the table is rewritten whole.
    assert build_silver.detect_gaps(out, RUN, today=DAY).rows == []
    assert core_silver.read(out, core_silver.DRAW_GAPS) == []


def test_quarantine_leaves_draw_gaps_as_it_was(tmp_path):
    lake, out = built(tmp_path)
    before = build_silver.detect_gaps(out, RUN, today=date(2016, 7, 31)).rows
    lake.put("extracto_quiniela_vespertina", DAY, b"<html>not an extract</html>")
    build_silver.rebuild(lake.manifest, lake.bronze, out, [2016], RUN)
    lake.manifest.close()

    report = build_silver.detect_gaps(out, RUN, today=date(2016, 12, 31))
    assert (report.rows, report.quarantine) == (None, 1)
    assert core_silver.read(out, core_silver.DRAW_GAPS) == sorted(before, key=lambda r: r["game"])
    assert build_silver.format_gaps(report) == (
        "draw_gaps: not rewritten, silver has 1 rows in quarantine"
    )


@pytest.mark.usefixtures("root_logger_restored")
def test_uy_silver_exits_1_when_quarantine_stops_the_detector(tmp_path, capsys):
    lake = Lake(tmp_path)
    lake.fixture("resultados", DAY)
    lake.put("extracto_quiniela_vespertina", DAY, b"<html>not an extract</html>")
    lake.manifest.close()
    assert build_silver.main(["--root", str(tmp_path), "--silver", str(tmp_path / "s")]) == 1
    assert "draw_gaps: not rewritten" in capsys.readouterr().err


# --- the incremental: the detector on every run, even with nothing new ---------------------


@pytest.mark.usefixtures("root_logger_restored")
def test_the_incremental_reruns_the_detector_when_nothing_changed(tmp_path, monkeypatch, capsys):
    from test_uy_backfill import FakeClient
    from test_uy_incremental import a_week, run_main

    from sorteos.uy import backfill

    client = FakeClient(a_week() | a_week(date(2016, 7, 12)))
    monkeypatch.setattr(backfill, "today_in_uruguay", lambda: date(2016, 7, 7))
    assert run_main(tmp_path, client) == 0
    assert "draw_gaps: 0 (0 explained, 0 open)" in capsys.readouterr().err

    # Days later the site has published no draw since: the windows of the Quinielas of
    # 2016-07-06 have closed (the 5 de Oro's has not yet), and the detector sees it.
    monkeypatch.setattr(backfill, "today_in_uruguay", lambda: date(2016, 7, 12))
    assert run_main(tmp_path, client) == 0
    assert "draw_gaps: 2 (0 explained, 2 open)" in capsys.readouterr().err

    # The 404 extracts close after three identical failures (D11); then nothing changes.
    for _ in range(3):
        run_main(tmp_path, client)
        if "silver: nothing changed" in capsys.readouterr().err:
            break
    (tmp_path / "silver" / "draw_gaps").rename(tmp_path / "gone")

    # Nothing changes, silver is left alone, and still the detector runs.
    assert run_main(tmp_path, client) == 0
    err = capsys.readouterr().err
    assert "silver: nothing changed" in err and "draw_gaps: 2 (0 explained, 2 open)" in err
    assert len(core_silver.read(tmp_path / "silver", core_silver.DRAW_GAPS)) == 2


@pytest.mark.usefixtures("root_logger_restored")
def test_the_incremental_exits_1_when_quarantine_stops_the_detector(tmp_path, monkeypatch):
    from test_uy_backfill import FakeClient
    from test_uy_incremental import a_week, run_main

    from sorteos.uy import backfill

    monkeypatch.setattr(backfill, "today_in_uruguay", lambda: date(2016, 7, 7))
    monkeypatch.setattr(
        build_silver, "detect_gaps", lambda *a: build_silver.GapReport(None, quarantine=1)
    )
    assert run_main(tmp_path, FakeClient(a_week())) == 1
