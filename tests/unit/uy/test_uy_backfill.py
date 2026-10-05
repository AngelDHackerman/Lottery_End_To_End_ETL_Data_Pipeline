"""Backfill orchestration, bronze store and manifest — against a fake client, no network."""

from __future__ import annotations

import argparse
import logging
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from loteria_uy import backfill, bronze, sources
from loteria_uy.http_client import FetchError, FetchResult

UY = Path(__file__).parents[2] / "fixtures" / "uy"
EMPTY_DAY = (UY / "resultados_2025-12-25.html").read_bytes()
DAY = date(2016, 7, 6)
POZOS = "https://www.loteria.gub.uy/invalidas/06072016/ORO_06072016_RES_INFORMACION_DE_POZOS.PDF"


def extract(day: date) -> bytes:
    return f"<html><body>EXTRACTO OFICIAL Miércoles {day:%d/%m/%Y} 701 099</body></html>".encode()


class FakeClient:
    """url -> (status, body) or an exception. Unknown URLs fail the test loudly."""

    def __init__(self, pages: dict):
        self.pages = pages
        self.calls: list[str] = []

    def get(self, url: str) -> FetchResult:
        self.calls.append(url)
        answer = self.pages[url]
        if isinstance(answer, Exception):
            raise answer
        status, body = answer
        headers = {"Content-Type": "text/html; charset=UTF-8"}
        if body.startswith(b"%PDF"):
            headers = {"Content-Type": "application/pdf", "Last-Modified": "Thu, 07 Jul 2016"}
        return FetchResult(url, url, status, headers, body, datetime.now(UTC), 0.01)


def july_2016() -> dict:
    pages = {
        sources.RESULTADOS.url(date(2016, 7, 5)): (200, EMPTY_DAY),
        sources.RESULTADOS.url(DAY): (200, (UY / "resultados_2016-07-06.html").read_bytes()),
        sources.RESULTADOS.url(date(2016, 7, 7)): (200, EMPTY_DAY),
        POZOS: (200, b"%PDF-1.4 pozos"),
    }
    for source in sources.EXTRACTOS_PHP:
        pages[source.url(DAY)] = (200, extract(DAY))
    return pages


@pytest.fixture
def stores(tmp_path):
    manifest = bronze.Manifest(tmp_path / "manifest.sqlite")
    yield bronze.BronzeStore(tmp_path), manifest
    manifest.close()


def job(client, stores, *, today=date(2026, 10, 4), srcs="resultados,extractos,pozos", **kw):
    store, manifest = stores
    return backfill.Backfill(
        client, store, manifest, sources=backfill.resolve_sources(srcs), today=today, **kw
    )


def test_a_draw_day_lands_every_source_in_bronze_and_empty_days_only_in_the_manifest(stores):
    client = FakeClient(july_2016())
    stats = job(client, stores).run(date(2016, 7, 5), date(2016, 7, 7))
    store, manifest = stores

    assert stats.requests == 3 + 3 + 1  # three days, three extracts, one pozos PDF
    assert stats.by_state == {"no_draw": 2, "draw": 5}
    row = manifest.get("resultados", DAY)
    assert row["games"] == ("quiniela_vespertina", "quiniela_nocturna", "5_de_oro")
    assert row["extra"] == {"pozos_url": POZOS}
    assert store.read(row["bronze_key"]) == client.pages[sources.RESULTADOS.url(DAY)][1]
    assert row["bronze_key"] == (
        "bronze/country=uy/source=resultados/year=2016/resultados_2016-07-06.html"
    )
    pozos = manifest.get("pozos_5_de_oro", DAY)
    assert pozos["bronze_key"].endswith("pozos_5_de_oro_2016-07-06.pdf")
    assert pozos["last_modified"] == "Thu, 07 Jul 2016"
    assert manifest.get("resultados", date(2016, 7, 5))["bronze_key"] is None
    assert not (
        store.root / "bronze/country=uy/source=resultados/year=2016/" "resultados_2016-07-05.html"
    ).exists()


def test_a_second_run_asks_for_nothing(stores):
    client = FakeClient(july_2016())
    job(client, stores).run(date(2016, 7, 5), date(2016, 7, 7))
    first = len(client.calls)
    stats = job(client, stores).run(date(2016, 7, 5), date(2016, 7, 7))
    assert len(client.calls) == first
    assert stats.requests == 0 and stats.skipped == 7


def test_refresh_fetches_again_and_counts_attempts(stores):
    client = FakeClient(july_2016())
    job(client, stores, srcs="resultados").run(DAY, DAY)
    job(client, stores, srcs="resultados", refresh=True).run(DAY, DAY)
    assert stores[1].get("resultados", DAY)["attempts"] == 2


def test_a_recent_empty_page_is_not_yet_published_and_is_retried(stores):
    today = date(2026, 10, 4)
    url = sources.RESULTADOS.url(today)
    client = FakeClient({url: (200, EMPTY_DAY)})
    job(client, stores, today=today).run(today, today)
    assert stores[1].get("resultados", today)["state"] == "not_yet_published"
    job(client, stores, today=today).run(today, today)
    assert client.calls == [url, url]


def test_an_empty_extract_for_a_listed_game_is_missing(stores):
    pages = july_2016()
    oro = next(s for s in sources.EXTRACTOS_PHP if s.game == "5_de_oro")
    pages[oro.url(DAY)] = (200, (UY / "extracto_5_de_oro_2025-09-16.html").read_bytes())
    job(FakeClient(pages), stores).run(DAY, DAY)
    row = stores[1].get("extracto_5_de_oro", DAY)
    assert row["state"] == "missing" and row["bronze_key"] is None


def test_fetch_failures_and_bad_statuses_are_errors_and_retried(stores):
    url = sources.RESULTADOS.url(DAY)
    client = FakeClient({url: FetchError("HTTP 503 after 6 attempts")})
    job(client, stores, srcs="resultados").run(DAY, DAY)
    assert stores[1].get("resultados", DAY)["state"] == "error"
    client.pages[url] = (403, b"forbidden")
    job(client, stores, srcs="resultados").run(DAY, DAY)
    row = stores[1].get("resultados", DAY)
    assert (row["state"], row["detail"], row["attempts"]) == ("error", "HTTP 403", 2)


def test_pdfs_are_only_requested_from_their_first_day(stores):
    day = date(2026, 10, 3)
    pdf = next(s for s in sources.EXTRACTOS_PDF if s.game == "quiniela_nocturna")
    client = FakeClient(
        {
            sources.RESULTADOS.url(day): (200, (UY / "resultados_2026-10-03.html").read_bytes()),
            pdf.url(day): (200, b"%PDF-1.7"),
        }
    )
    job(client, stores, srcs="resultados,pdf").run(day, day)
    assert stores[1].get("extracto_pdf_quiniela_nocturna", day)["state"] == "draw"
    assert stores[1].get("extracto_pdf_5_de_oro", day) is None  # not drawn that day

    early = FakeClient(july_2016())
    job(early, stores, srcs="resultados,pdf").run(DAY, DAY)
    assert early.calls == [sources.RESULTADOS.url(DAY)]


def test_the_request_budget_stops_the_run(stores):
    client = FakeClient(july_2016())
    stats = job(client, stores, max_requests=2).run(date(2016, 7, 5), date(2016, 7, 7))
    assert stats.requests == 2 and len(client.calls) == 2


def test_the_end_is_clamped_to_today_in_uruguay(stores):
    client = FakeClient({sources.RESULTADOS.url(date(2016, 7, 5)): (200, EMPTY_DAY)})
    job(client, stores, today=date(2016, 7, 5), srcs="resultados").run(
        date(2016, 7, 5), date(2030, 1, 1)
    )
    assert len(client.calls) == 1


def test_resolve_sources():
    names = [s.name for s in backfill.resolve_sources("resultados, extracto_5_de_oro,extractos")]
    assert names == [
        "resultados",
        "extracto_5_de_oro",
        "extracto_quiniela_vespertina",
        "extracto_quiniela_nocturna",
    ]
    with pytest.raises(argparse.ArgumentTypeError):
        backfill.resolve_sources("everything")


def test_parse_day(monkeypatch):
    monkeypatch.setattr(backfill, "today_in_uruguay", lambda: date(2026, 10, 4))
    assert backfill.parse_day("today") == date(2026, 10, 4)
    assert backfill.parse_day("2006-08-11") == date(2006, 8, 11)


def test_today_in_uruguay_is_a_date():
    assert isinstance(backfill.today_in_uruguay(), date)


def test_main_runs_and_reports(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(backfill, "today_in_uruguay", lambda: date(2026, 10, 4))
    # main() installs the JSON handler on the root logger, bound to capsys's stream; put the
    # old handlers back afterwards or every later test logs into a closed file.
    monkeypatch.setattr(logging.getLogger(), "handlers", list(logging.getLogger().handlers))
    client = FakeClient(july_2016())
    argv = [
        "--start",
        "2016-07-05",
        "--end",
        "2016-07-07",
        "--root",
        str(tmp_path),
        "--sources",
        "resultados,extractos,pozos",
    ]
    assert backfill.main(argv, client=client) == 0
    report = capsys.readouterr().err
    assert "resultados" in report and "no_draw" in report
    assert "resultados: draws from 2016-07-06 to 2016-07-06" in report

    assert backfill.main(["--report", "--root", str(tmp_path)], client=client) == 0
    assert len(client.calls) == 7  # --report requested nothing


def test_manifest_keeps_a_log_of_every_attempt(stores):
    _, manifest = stores
    rec = bronze.Record("resultados", DAY, "u", "error", "2026-10-04T00:00:00+00:00")
    manifest.record(rec)
    manifest.record(rec)
    assert manifest._db.execute("SELECT COUNT(*) FROM fetch_log").fetchone()[0] == 2
    assert manifest.get("resultados", DAY)["attempts"] == 2
    assert manifest.date_range("resultados") is None


def test_bronze_write_is_atomic(tmp_path):
    store = bronze.BronzeStore(tmp_path)
    key = store.key("resultados", DAY, "html")
    store.write(key, b"one")
    store.write(key, b"two")
    assert store.read(key) == b"two"
    assert not list(tmp_path.rglob("*.tmp"))
