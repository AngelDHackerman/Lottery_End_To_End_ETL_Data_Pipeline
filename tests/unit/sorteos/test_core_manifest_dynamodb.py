"""What only the DynamoDB manifest has to get right (UY-042.2). The shared contract is in
test_core_manifest.py, which runs against both backends."""

from __future__ import annotations

from datetime import date

import pytest

from sorteos.core import manifest as mf
from sorteos.core import manifest_dynamodb as md

TABLE = "lottery-uy-manifest-test"  # the table the `dynamodb` fixture creates (conftest.py)
DAY = date(2019, 9, 25)
NOW = "2026-10-28T00:00:00+00:00"


def items(client):
    return [
        md.from_dynamo(raw, ("pk", "sk", "open", "state"))
        for raw in client.scan(TableName=TABLE)["Items"]
    ]


def test_a_key_is_in_the_open_index_only_while_it_is_not_final(dynamodb):
    m = md.DynamoManifest(TABLE, client=dynamodb)
    m.record(mf.Record("resultados", DAY, "u", mf.NOT_YET_PUBLISHED, NOW))
    state = next(i for i in items(dynamodb) if i["sk"] == md.STATE_SK)
    assert state["open"] == md.OPEN
    m.record(mf.Record("resultados", DAY, "u", mf.DRAW, "2026-10-29T00:00:00+00:00"))
    state = next(i for i in items(dynamodb) if i["sk"] == md.STATE_SK)
    assert state["open"] is None
    assert m.open_keys() == []


def test_get_returns_every_column_with_sqlite_types(dynamodb):
    m = md.DynamoManifest(TABLE, client=dynamodb)
    m.record(
        mf.Record(
            "resultados",
            DAY,
            "u",
            mf.DRAW,
            NOW,
            http_status=200,
            content=b"<html/>",
            games=("5_de_oro",),
            extra={"k": 1},
        )
    )
    row = m.get("resultados", DAY)
    assert set(row) == set(md.MANIFEST_COLUMNS)
    assert row["http_status"] == 200 and type(row["http_status"]) is int
    assert row["bytes"] == 7 and row["attempts"] == 1
    assert row["games"] == ("5_de_oro",) and row["extra"] == {"k": 1}
    assert row["bronze_key"] is None and row["first_fetched_at"] == NOW
    assert m.get("resultados", date(2019, 9, 24)) is None


def test_the_first_fetch_is_kept_across_attempts(dynamodb):
    m = md.DynamoManifest(TABLE, client=dynamodb)
    m.record(mf.Record("resultados", DAY, "u", mf.ERROR, NOW))
    m.record(mf.Record("resultados", DAY, "u", mf.DRAW, "2026-10-29T00:00:00+00:00"))
    row = m.get("resultados", DAY)
    assert row["first_fetched_at"] == NOW and row["attempts"] == 2
    logs = sorted(i["sk"] for i in items(dynamodb) if i["sk"].startswith(md.LOG_PREFIX))
    assert logs == [f"LOG#{NOW}#000001", "LOG#2026-10-29T00:00:00+00:00#000002"]


def test_two_runs_on_one_key_never_lose_a_row(dynamodb, monkeypatch):
    first = md.DynamoManifest(TABLE, client=dynamodb)
    second = md.DynamoManifest(TABLE, client=dynamodb)
    first.record(mf.Record("resultados", DAY, "u", mf.ERROR, NOW))
    # `second` read the key before `first` wrote it: it still believes the key is new.
    monkeypatch.setattr(second, "_state", lambda source, day: None)
    with pytest.raises(md.ConcurrentWriteError, match="run again"):
        second.record(mf.Record("resultados", DAY, "u", mf.DRAW, NOW))
    assert first.get("resultados", DAY)["state"] == mf.ERROR
    assert len(first.history("resultados", DAY, 10)) == 1


def test_a_stale_attempt_count_is_refused_too(dynamodb, monkeypatch):
    m = md.DynamoManifest(TABLE, client=dynamodb)
    m.record(mf.Record("resultados", DAY, "u", mf.ERROR, NOW))
    m.record(mf.Record("resultados", DAY, "u", mf.ERROR, NOW))
    real = m._state
    stale = {**real("resultados", DAY.isoformat()), "attempts": 1}
    monkeypatch.setattr(m, "_state", lambda source, day: stale)
    with pytest.raises(md.ConcurrentWriteError):
        m.record(mf.Record("resultados", DAY, "u", mf.DRAW, NOW))
    assert real("resultados", DAY.isoformat())["attempts"] == 2


def test_history_with_no_limit_reads_nothing(dynamodb):
    assert md.DynamoManifest(TABLE, client=dynamodb).history("resultados", DAY, 0) == []


# --- the snapshot (UY-042.4.1) -----------------------------------------------------------


def test_a_snapshot_answers_like_the_table_it_was_taken_from(dynamodb):
    strike = date(2019, 9, 26)
    overrides = {
        ("resultados", strike): mf.Override(
            "resultados", strike, mf.NO_DRAW, strike, "paro", "owner", date(2026, 10, 20)
        )
    }
    m = md.DynamoManifest(TABLE, overrides, client=dynamodb)
    m.record(mf.Record("resultados", DAY, "u", mf.DRAW, NOW, content=b"x", games=("5_de_oro",)))
    m.record(mf.Record("resultados", date(2019, 9, 27), "u", mf.DRAW, NOW, content=b"y"))
    m.record(mf.Record("resultados", strike, "u", mf.ERROR, NOW))
    m.record(mf.Record("pozos_5_de_oro", DAY, "u", mf.NOT_YET_PUBLISHED, NOW))
    snap = m.snapshot()
    assert len(snap) == 4
    for source, day in (("resultados", DAY), ("pozos_5_de_oro", DAY), ("resultados", strike)):
        assert snap.get(source, day) == m.get(source, day)
        assert snap.effective_state(source, day) == m.effective_state(source, day)
    assert snap.get("resultados", date(2001, 1, 1)) is None
    assert snap.summary() == m.summary()
    assert (
        snap.date_range("resultados")
        == m.date_range("resultados")
        == (
            "2019-09-25",
            "2019-09-27",
        )
    )
    assert snap.date_range("extracto_5_de_oro") is None
    assert snap.open_keys() == m.open_keys() == [("pozos_5_de_oro", DAY)]
    assert [r["draw_date"] for r in snap.rows()][:1] == ["2019-09-25"]
    snap.close()


def test_a_snapshot_never_writes(dynamodb):
    snap = md.DynamoManifest(TABLE, client=dynamodb).snapshot()
    with pytest.raises(md.ReadOnlyManifestError):
        snap.record(mf.Record("resultados", DAY, "u", mf.DRAW, NOW))
    with pytest.raises(md.ReadOnlyManifestError):
        snap.history("resultados", DAY, 3)
