"""The manifest contract: three identical failures, manual overrides and the effective state."""

from __future__ import annotations

import sqlite3
from datetime import date

import pytest

from sorteos.core import manifest as mf
from sorteos.uy import backfill

DAY = date(2019, 9, 25)
NOW = "2026-10-28T00:00:00+00:00"
FORBIDDEN = b"<html>403 Forbidden</html>"  # one body, so one content_sha256

# The schema the ~21,000-row local manifest was created with (UY-001). Frozen here on purpose:
# if SqliteManifest ever needs another column, this test says the old file needs a migration.
UY001_SCHEMA = """
CREATE TABLE manifest (
    source TEXT NOT NULL, draw_date TEXT NOT NULL, url TEXT NOT NULL, state TEXT NOT NULL,
    http_status INTEGER, games TEXT, warnings TEXT, extra TEXT, detail TEXT,
    content_sha256 TEXT, bytes INTEGER, bronze_key TEXT, content_type TEXT,
    last_modified TEXT, classifier_version TEXT, attempts INTEGER NOT NULL DEFAULT 0,
    first_fetched_at TEXT NOT NULL, fetched_at TEXT NOT NULL, PRIMARY KEY (source, draw_date)
);
CREATE TABLE fetch_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, source TEXT NOT NULL, draw_date TEXT NOT NULL,
    url TEXT NOT NULL, state TEXT NOT NULL, http_status INTEGER, content_sha256 TEXT,
    detail TEXT, fetched_at TEXT NOT NULL
);
"""


@pytest.fixture
def manifest(tmp_path):
    m = mf.SqliteManifest(tmp_path / "manifest.sqlite")
    yield m
    m.close()


def failure(status=403, content=FORBIDDEN, detail="HTTP 403, 26 bytes, not a PDF", day=DAY):
    return mf.Record(
        "pozos_5_de_oro",
        day,
        "u",
        mf.ERROR,
        NOW,
        http_status=status,
        content=content,
        detail=detail,
    )


def test_the_third_identical_failure_closes_the_key_as_missing(manifest):
    assert manifest.record(failure()) == mf.ERROR
    assert manifest.record(failure()) == mf.ERROR
    assert manifest.record(failure()) == mf.MISSING
    row = manifest.get("pozos_5_de_oro", DAY)
    assert row["state"] == mf.MISSING and row["attempts"] == 3
    assert row["detail"] == "same failure 3 times in a row: HTTP 403, 26 bytes, not a PDF"
    # The log keeps what each fetch saw, so the signatures stay comparable.
    assert [r["state"] for r in manifest.history("pozos_5_de_oro", DAY, 10)] == [mf.ERROR] * 3
    assert manifest.history("pozos_5_de_oro", DAY, 10)[-1]["detail"] == failure().detail


def test_an_empty_200_has_a_stable_signature_too(manifest):
    empty = failure(status=200, content=b"", detail="HTTP 200, 0 bytes, not a PDF")
    assert [manifest.record(empty) for _ in range(3)] == [mf.ERROR, mf.ERROR, mf.MISSING]


@pytest.mark.parametrize(
    "third",
    [
        failure(content=b"<html>403, another body</html>"),  # same status, another body
        failure(status=404),
        failure(status=None, content=None, detail="ConnectTimeout after 6 attempts"),
    ],
)
def test_a_different_failure_does_not_count(manifest, third):
    manifest.record(failure())
    manifest.record(failure())
    assert manifest.record(third) == mf.ERROR


def test_only_the_last_failures_count(manifest):
    manifest.record(failure())
    manifest.record(failure())
    manifest.record(mf.Record("pozos_5_de_oro", DAY, "u", mf.NOT_YET_PUBLISHED, NOW))
    assert manifest.record(failure()) == mf.ERROR
    assert manifest.record(failure()) == mf.ERROR
    assert manifest.record(failure()) == mf.MISSING


def test_timeouts_count_by_their_detail(manifest):
    timeout = failure(status=None, content=None, detail="ReadTimeout after 6 attempts")
    other = failure(status=None, content=None, detail="ConnectError after 6 attempts")
    manifest.record(timeout)
    manifest.record(other)
    assert manifest.record(timeout) == mf.ERROR
    manifest.record(timeout)
    assert manifest.record(timeout) == mf.MISSING


def test_failures_of_another_key_do_not_count(manifest):
    manifest.record(failure(day=date(2019, 9, 24)))
    manifest.record(failure(day=date(2019, 9, 24)))
    assert manifest.record(failure()) == mf.ERROR


def test_history_is_the_last_rows_oldest_first(manifest):
    for detail in ("a", "b", "c"):
        manifest.record(failure(detail=detail))
    assert [r["detail"] for r in manifest.history("pozos_5_de_oro", DAY, 2)] == ["b", "c"]
    assert manifest.history("resultados", DAY, 2) == []


def override(state=mf.NO_DRAW):
    return mf.Override("resultados", DAY, state, DAY, "paro", "owner", date(2026, 10, 20))


def test_the_effective_state_is_the_override_when_there_is_one(tmp_path):
    m = mf.SqliteManifest(tmp_path / "m.sqlite", {("resultados", DAY): override()})
    rec = mf.Record("resultados", DAY, "u", mf.ERROR, NOW, http_status=200, content=b"x")
    m.record(rec)
    assert m.effective_state("resultados", DAY) == mf.NO_DRAW
    assert m.get("resultados", DAY)["state"] == mf.ERROR  # what the classifier saw stays
    assert m.effective_state("resultados", date(2019, 9, 24)) is None
    m.close()


def test_an_override_applies_before_the_key_is_ever_fetched(tmp_path):
    m = mf.SqliteManifest(tmp_path / "m.sqlite", {("resultados", DAY): override()})
    assert m.effective_state("resultados", DAY) == mf.NO_DRAW
    m.close()


def test_a_manifest_with_the_uy001_schema_is_read_without_migrating(tmp_path):
    path = tmp_path / "manifest.sqlite"
    db = sqlite3.connect(path)
    db.executescript(UY001_SCHEMA)
    db.execute(
        "INSERT INTO manifest (source, draw_date, url, state, games, warnings, extra, attempts,"
        " first_fetched_at, fetched_at) VALUES ('resultados', '2019-09-25', 'u', 'error',"
        " '[]', '[]', '{}', 2, ?, ?)",
        (NOW, NOW),
    )
    db.commit()
    before = db.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall()
    db.close()

    m = mf.SqliteManifest(path, {("resultados", DAY): override()})
    assert m.get("resultados", DAY)["attempts"] == 2
    assert m.effective_state("resultados", DAY) == mf.NO_DRAW
    m.close()
    db = sqlite3.connect(path)
    assert db.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall() == before
    db.close()


# --- manual_overrides.csv --------------------------------------------------------------------

HEADER = "source,draw_date,state,calendar_event_date,reason,decided_by,decided_on\n"
GOOD = "resultados,2019-09-25,no_draw,2019-09-25,paro (OIS 2036),owner,2026-10-20\n"


@pytest.fixture
def calendar(tmp_path):
    path = tmp_path / "calendar_events.csv"
    path.write_text("event_date,games\n2019-09-25,quiniela_nocturna\n", encoding="utf-8")
    return path


def load(tmp_path, calendar, text):
    path = tmp_path / "manual_overrides.csv"
    path.write_text(text, encoding="utf-8")
    return mf.load_overrides(path, calendar_events=calendar, sources={"resultados"})


def test_a_valid_override_loads(tmp_path, calendar):
    assert load(tmp_path, calendar, HEADER + GOOD) == {
        ("resultados", DAY): mf.Override(
            "resultados", DAY, "no_draw", DAY, "paro (OIS 2036)", "owner", date(2026, 10, 20)
        )
    }


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        (HEADER.replace("reason,", "") + GOOD, "columns must be"),
        (HEADER + GOOD + GOOD, "already overridden"),
        (HEADER + GOOD.replace("resultados", "extracto_kini"), "unknown source"),
        (HEADER + GOOD.replace("no_draw", "draw"), "state must be one of"),
        (HEADER + GOOD.replace("no_draw", "error"), "state must be one of"),
        (HEADER + GOOD.replace("09-25,paro", "09-26,paro"), "is not in calendar_events.csv"),
        (HEADER + GOOD.replace("2026-10-20", "20/10/2026"), "is not a YYYY-MM-DD date"),
        (HEADER + GOOD.replace("resultados,2019-09-25", "resultados,2019-9-25"), "YYYY-MM-DD"),
        (HEADER + GOOD.replace(",owner,", ",,"), "every column needs a value"),
        (HEADER + GOOD.replace("\n", ",extra\n"), "no more columns"),
    ],
)
def test_a_bad_override_fails_at_load(tmp_path, calendar, text, problem):
    with pytest.raises(mf.OverrideError, match=problem):
        load(tmp_path, calendar, text)


def test_the_repo_overrides_are_the_four_strike_days():
    overrides = backfill.load_overrides()
    assert sorted(overrides) == [("resultados", date(2019, 9, d)) for d in (25, 26, 27, 30)]
    assert {o.state for o in overrides.values()} == {mf.NO_DRAW}
    assert all(o.calendar_event_date == o.draw_date for o in overrides.values())
