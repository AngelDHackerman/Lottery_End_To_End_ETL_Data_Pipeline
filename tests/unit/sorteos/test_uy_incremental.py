"""UY-027.1: the incremental and ``uy-silver`` — against a fake client and fixture pages."""

from __future__ import annotations

import argparse
import json
from datetime import date, timedelta

import pyarrow.parquet as pq
import pytest
from test_uy_backfill import (  # pytest puts this directory on sys.path
    DAY,
    EMPTY_DAY,
    POZOS,
    UY,
    FakeClient,
    job,
    july_2016,
    root_logger_restored,  # noqa: F401 (a fixture)
)
from test_uy_silver import Lake

from sorteos.core import manifest as mf
from sorteos.uy import backfill, build_silver, incremental, sources

TODAY = date(2016, 7, 7)  # DAY (2016-07-06) is a draw day of all three games
NOW = "2026-10-29T00:00:00+00:00"


@pytest.fixture
def stores(tmp_path):
    lake = Lake(tmp_path)
    yield lake.bronze, lake.manifest
    lake.manifest.close()


def a_week(today: date = TODAY) -> dict:
    """july_2016() plus empty results pages for the rest of the 7-day window.

    Its fake extracts and pozos PDF answer 404 here: as ``draw`` they would not parse and
    would send the three draws to quarantine (owner, UY-025 2a), and silver would be empty.
    """
    pages = july_2016()
    for source in sources.EXTRACTOS_PHP:
        pages[source.url(DAY)] = (404, b"not found")
    pages[POZOS] = (404, b"not found")
    for back in range(incremental.WINDOW_DAYS):
        pages.setdefault(sources.RESULTADOS.url(today - timedelta(days=back)), (200, EMPTY_DAY))
    return pages


# --- what the backfill reports as changed -------------------------------------------------


def test_every_new_key_is_changed_and_a_second_run_changes_nothing(stores):
    client = FakeClient(july_2016())
    stats = job(client, stores).run(date(2016, 7, 5), date(2016, 7, 7))
    assert stats.changed == {
        ("resultados", date(2016, 7, 5)),
        ("resultados", DAY),
        ("resultados", date(2016, 7, 7)),
        *((s.name, DAY) for s in sources.EXTRACTOS_PHP),
        ("pozos_5_de_oro", DAY),
    }
    assert job(client, stores).run(date(2016, 7, 5), date(2016, 7, 7)).changed == set()


def test_the_same_failure_again_is_no_change_until_it_closes_the_key(stores):
    pages = july_2016()
    pages[POZOS] = (403, b"<html><body>403 Forbidden</body></html>")
    client = FakeClient(pages)
    runs = [job(client, stores, srcs="resultados,pozos").run(DAY, DAY) for _ in range(3)]
    assert ("pozos_5_de_oro", DAY) in runs[0].changed  # new: error
    assert runs[1].changed == set()  # error again, same body
    assert runs[2].changed == {("pozos_5_de_oro", DAY)}  # error -> missing (D11)


def test_a_page_whose_content_moves_is_changed_even_in_the_same_state(stores):
    client = FakeClient(july_2016())
    job(client, stores, srcs="resultados").run(DAY, DAY)
    other = (UY / "resultados_2016-07-06.html").read_bytes() + b"\n"
    client.pages[sources.RESULTADOS.url(DAY)] = (200, other)
    stats = job(client, stores, srcs="resultados", refresh=True).run(DAY, DAY)
    assert stats.changed == {("resultados", DAY)}


def test_run_keys_asks_for_that_key_only(stores):
    # An old open extract must not bring the extract PDFs of its day with it (D19).
    day = date(2018, 12, 29)
    page = (UY / f"resultados_{day}.html").read_bytes()
    client = FakeClient({sources.RESULTADOS.url(day): (200, page)})
    job(client, stores, srcs="resultados").run(day, day)
    assert "quiniela_nocturna" in stores[1].get("resultados", day)["games"]
    php = next(s for s in sources.EXTRACTOS_PHP if s.game == "quiniela_nocturna")
    stores[1].record(mf.Record(php.name, day, php.url(day), mf.ERROR, NOW, detail="timeout"))
    client.pages[php.url(day)] = (200, b"<html><body>EXTRACTO OFICIAL 29/12/2018</body></html>")
    client.calls.clear()

    stats = job(client, stores, srcs=incremental.SOURCES).run_keys([(php.name, day)])
    assert client.calls == [php.url(day)]
    assert stats.changed == {(php.name, day)}


def test_run_keys_skips_a_key_closed_in_between_and_stops_at_the_budget(stores):
    client = FakeClient(july_2016())
    job(client, stores, srcs="resultados").run(DAY, DAY)
    keys = [("resultados", DAY), *((s.name, DAY) for s in sources.EXTRACTOS_PHP)]
    stats = job(client, stores, max_requests=1).run_keys(keys)
    assert stats.skipped == 1 and stats.requests == 1


# --- the window ---------------------------------------------------------------------------


def test_the_window_is_the_last_7_days(stores):
    assert incremental.window_start(stores[1], TODAY) == date(2016, 7, 1)  # empty manifest
    stores[1].record(mf.Record("resultados", date(2016, 7, 3), "u", mf.DRAW, NOW))
    assert incremental.window_start(stores[1], TODAY) == date(2016, 7, 1)


def test_the_window_reaches_back_to_the_day_after_the_last_draw(stores):
    stores[1].record(mf.Record("resultados", date(2016, 6, 20), "u", mf.DRAW, NOW))
    assert incremental.window_start(stores[1], TODAY) == date(2016, 6, 21)


# --- main ---------------------------------------------------------------------------------


@pytest.fixture
def today(monkeypatch):
    monkeypatch.setattr(backfill, "today_in_uruguay", lambda: TODAY)


def run_main(tmp_path, client, *extra):
    argv = ["--root", str(tmp_path), "--silver", str(tmp_path / "silver"), *extra]
    return incremental.main(argv, client=client)


@pytest.mark.usefixtures("today", "root_logger_restored")
def test_main_fetches_the_window_and_old_open_keys_then_rewrites_silver(tmp_path, capsys):
    old = date(2016, 3, 15)
    m = mf.SqliteManifest(tmp_path / "manifest.sqlite")
    m.record(mf.Record("resultados", old, sources.RESULTADOS.url(old), mf.ERROR, NOW))
    m.close()
    client = FakeClient({**a_week(), sources.RESULTADOS.url(old): (200, EMPTY_DAY)})

    assert run_main(tmp_path, client) == 0
    window = [sources.RESULTADOS.url(TODAY - timedelta(days=b)) for b in range(7)]
    assert set(window) <= set(client.calls)
    assert client.calls[-1] == sources.RESULTADOS.url(old)  # the open key, after the window
    assert len(client.calls) == 7 + 3 + 1 + 1  # 7 days, 3 extracts, 1 pozos, 1 open key
    err = capsys.readouterr().err
    assert "window 2016-07-01 .. 2016-07-07, open keys before it: 1" in err
    assert "changed resultados 2016-03-15" in err

    draws = pq.read_table(tmp_path / "silver" / "draws").to_pylist()
    assert {(d["game"], d["draw_date"]) for d in draws} == {
        (g, DAY) for g in ("quiniela_vespertina", "quiniela_nocturna", "5_de_oro")
    }
    assert {d["run_id"][:15] for d in draws} == {"uy-incremental-"}
    assert not (tmp_path / incremental.PENDING).exists()


@pytest.mark.usefixtures("today", "root_logger_restored")
def test_a_run_with_nothing_new_leaves_silver_alone(tmp_path, capsys):
    client = FakeClient(a_week())
    run_main(tmp_path, client)
    capsys.readouterr()
    first = len(client.calls)
    assert run_main(tmp_path, client) == 0
    # Back come the 2 empty days not settled yet (not_yet_published), the 3 extracts and the
    # pozos PDF in error; the draw day and the settled empty days are final.
    assert len(client.calls) - first == 2 + 3 + 1
    assert "silver: nothing changed" in capsys.readouterr().err


@pytest.mark.usefixtures("today", "root_logger_restored")
def test_years_left_pending_by_a_failed_silver_are_rewritten_next_time(
    tmp_path, monkeypatch, capsys
):
    client = FakeClient(a_week())
    real = build_silver.rebuild

    def broken(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(build_silver, "rebuild", broken)
    with pytest.raises(RuntimeError):
        run_main(tmp_path, client)
    assert json.loads((tmp_path / incremental.PENDING).read_text()) == [2016]

    monkeypatch.setattr(build_silver, "rebuild", real)
    capsys.readouterr()
    run_main(tmp_path, client)
    err = capsys.readouterr().err
    assert "changed 0" in err and "silver: nothing changed" not in err
    assert (tmp_path / "silver" / "draws").exists()
    assert not (tmp_path / incremental.PENDING).exists()


@pytest.mark.usefixtures("today", "root_logger_restored")
def test_main_builds_its_client_through_the_privacy_module(tmp_path, monkeypatch):
    built = []

    def polite_client(**kwargs):
        built.append(kwargs)
        return FakeClient(a_week())

    monkeypatch.setattr(backfill.privacy, "polite_client", polite_client)
    assert incremental.main(["--root", str(tmp_path), "--max-requests", "1"]) == 0
    assert built == [{}]


# --- uy-silver ----------------------------------------------------------------------------


def test_rebuild_writes_each_year_and_counts_its_rows_and_flags(tmp_path):
    lake = Lake(tmp_path)
    lake.fixture("resultados", date(2006, 12, 6))  # pozo_plata_equals_oro
    lake.fixture("resultados", date(2016, 7, 6))
    run = build_silver.new_run("silver")
    counts = build_silver.rebuild(lake.manifest, lake.bronze, tmp_path / "s", [2006, 2016], run)
    lake.manifest.close()

    assert [c.year for c in counts] == [2006, 2016]
    assert counts[1].draws == 3 and counts[1].quarantine == 0
    assert counts[0].flags["pozo_plata_equals_oro"] == 1
    assert (tmp_path / "s" / "game_rules").exists()  # the reference tables come with it
    text = build_silver.format_counts(counts)
    assert "flag pozo_plata_equals_oro: 1" in text
    assert text.splitlines()[-2].split()[0] == "all"


def test_a_year_without_draws_loses_its_partition(tmp_path):
    lake = Lake(tmp_path)
    lake.fixture("resultados", date(2016, 7, 6))
    run = build_silver.new_run("silver")
    build_silver.rebuild(lake.manifest, lake.bronze, tmp_path / "s", [2016], run)
    lake.manifest.record(mf.Record("resultados", date(2016, 7, 6), "u", mf.NO_DRAW, NOW))
    build_silver.rebuild(lake.manifest, lake.bronze, tmp_path / "s", [2016], run)
    lake.manifest.close()
    assert not list((tmp_path / "s" / "draws").rglob("*.parquet"))


def test_new_run_names_the_kind_and_the_time():
    run = build_silver.new_run("silver")
    assert run.run_id == f"uy-silver-{run.ingested_at:%Y%m%dT%H%M%SZ}"


def test_all_years_spans_the_manifest(tmp_path):
    lake = Lake(tmp_path)
    assert build_silver.all_years(lake.manifest) == []
    lake.manifest.record(mf.Record("resultados", date(2006, 8, 11), "u", mf.DRAW, NOW))
    lake.manifest.record(mf.Record("resultados", date(2009, 1, 2), "u", mf.DRAW, NOW))
    assert build_silver.all_years(lake.manifest) == [2006, 2007, 2008, 2009]
    lake.manifest.close()


def test_parse_years():
    assert build_silver.parse_years("2016") == [2016]
    assert build_silver.parse_years("2026, 2014-2016,2015") == [2014, 2015, 2016, 2026]
    for bad in ("", "dos mil", "2016-x", ","):
        with pytest.raises(argparse.ArgumentTypeError):
            build_silver.parse_years(bad)


@pytest.mark.usefixtures("root_logger_restored")
def test_silver_main_defaults_to_every_year(tmp_path, capsys):
    lake = Lake(tmp_path)
    lake.fixture("resultados", date(2016, 7, 6))
    lake.manifest.close()
    out = tmp_path / "s"
    argv = ["--root", str(tmp_path), "--silver", str(out)]
    assert build_silver.main(argv) == 0
    assert "2016       3" in capsys.readouterr().err
    assert build_silver.main([*argv, "--years", "2015"]) == 0
    assert "2015       0" in capsys.readouterr().err
