"""Tests for the one-time copy of the manifest to DynamoDB (UY-042.2).

What has to hold: after the copy, the table answers exactly what SQLite answers, row by row and
through the Manifest interface; a second run writes nothing; and once the cloud has fetched
something the local file does not know, the copy refuses to write.
"""

from __future__ import annotations

from datetime import date

import pytest

from sorteos.core import manifest as mf
from sorteos.core import manifest_dynamodb as md
from sorteos.uy import manifest_migrate as mm

TABLE = "lottery-uy-manifest-test"  # the table the `dynamodb` fixture creates (conftest.py)
T1 = "2026-10-04T14:43:31+00:00"
T2 = "2026-10-05T14:43:31+00:00"
T3 = "2026-10-06T14:43:31+00:00"
STRIKE = date(2019, 9, 25)
OVERRIDES = {
    ("resultados", STRIKE): mf.Override(
        "resultados", STRIKE, mf.NO_DRAW, STRIKE, "paro", "owner", date(2026, 10, 20)
    )
}


@pytest.fixture
def sqlite(tmp_path):
    path = tmp_path / "manifest.sqlite"
    m = mf.SqliteManifest(path)
    m.record(
        mf.Record(
            "resultados",
            date(2016, 7, 6),
            "u",
            mf.DRAW,
            T1,
            http_status=200,
            content=b"<html/>",
            games=("5_de_oro",),
            bronze_key="bronze/k.html",
        )
    )
    m.record(mf.Record("resultados", date(2016, 7, 7), "u", mf.NO_DRAW, T1, http_status=200))
    m.record(mf.Record("resultados", STRIKE, "u", mf.ERROR, T1))  # closed by the override
    for at in (T1, T2, T3):  # three identical failures: missing
        m.record(
            mf.Record("pozos_5_de_oro", STRIKE, "u", mf.ERROR, at, http_status=403, content=b"no")
        )
    m.record(mf.Record("resultados", date(2026, 11, 3), "u", mf.NOT_YET_PUBLISHED, T3))
    m.close()
    return path


def migrate(sqlite, dynamodb, *extra):
    return mm.main(
        ["--sqlite", str(sqlite), "--table", TABLE, *extra], client=dynamodb, overrides=OVERRIDES
    )


def test_the_copy_answers_like_sqlite(sqlite, dynamodb, capsys):
    assert migrate(sqlite, dynamodb) == 0
    out = capsys.readouterr().out
    assert "5 STATE        7 LOG  (after)" in out
    assert "OK: the table is the local manifest" in out
    local = mf.SqliteManifest(sqlite, OVERRIDES)
    cloud = md.DynamoManifest(TABLE, OVERRIDES, client=dynamodb)
    for source, day in (("pozos_5_de_oro", STRIKE), ("resultados", date(2016, 7, 6))):
        assert cloud.get(source, day) == local.get(source, day)
        assert cloud.history(source, day, 5) == [
            {k: r[k] for k in md.LOG_COLUMNS} for r in local.history(source, day, 5)
        ]
    assert cloud.open_keys() == [("resultados", date(2026, 11, 3))]
    local.close()


def test_the_pending_item_is_not_a_manifest_row(sqlite, dynamodb, capsys):
    assert migrate(sqlite, dynamodb) == 0
    md.PendingYears(TABLE, dynamodb).add({2026})  # UY-043.2: the fetch Lambda's bookkeeping
    capsys.readouterr()
    assert migrate(sqlite, dynamodb, "--check") == 0
    assert "OK: the table is the local manifest" in capsys.readouterr().out


def test_a_migrated_key_keeps_counting_failures_in_the_cloud(sqlite, dynamodb):
    migrate(sqlite, dynamodb)
    cloud = md.DynamoManifest(TABLE, client=dynamodb)
    day = date(2026, 11, 3)
    for at in ("2026-11-04T00:00:00+00:00", "2026-11-05T00:00:00+00:00"):
        cloud.record(mf.Record("resultados", day, "u", mf.ERROR, at, http_status=500, content=b"x"))
    assert (
        cloud.record(
            mf.Record(
                "resultados",
                day,
                "u",
                mf.ERROR,
                "2026-11-06T00:00:00+00:00",
                http_status=500,
                content=b"x",
            )
        )
        == mf.MISSING
    )
    assert cloud.get("resultados", day)["attempts"] == 4


def test_a_second_run_writes_nothing(sqlite, dynamodb, capsys):
    migrate(sqlite, dynamodb)
    capsys.readouterr()
    assert migrate(sqlite, dynamodb) == 0
    assert "writing:       0 items" in capsys.readouterr().out


def test_a_run_that_stopped_halfway_finishes_the_rest(sqlite, dynamodb, capsys):
    migrate(sqlite, dynamodb)
    key = md.to_dynamo({"pk": "resultados#2016-07-06", "sk": md.STATE_SK})
    dynamodb.delete_item(TableName=TABLE, Key=key)
    capsys.readouterr()
    assert migrate(sqlite, dynamodb) == 0
    assert "writing:       1 items" in capsys.readouterr().out


def test_check_writes_nothing_and_fails_on_an_empty_table(sqlite, dynamodb, capsys):
    assert migrate(sqlite, dynamodb, "--check") == 1
    assert dynamodb.scan(TableName=TABLE)["Count"] == 0
    assert "missing: resultados#2016-07-06 STATE" in capsys.readouterr().out


def test_a_changed_item_fails_the_check(sqlite, dynamodb, capsys):
    migrate(sqlite, dynamodb)
    dynamodb.update_item(
        TableName=TABLE,
        Key=md.to_dynamo({"pk": "resultados#2016-07-07", "sk": md.STATE_SK}),
        UpdateExpression="SET detail = :d",
        ExpressionAttributeValues=md.to_dynamo({":d": "edited"}),
    )
    capsys.readouterr()
    assert migrate(sqlite, dynamodb, "--check") == 1
    assert "different: resultados#2016-07-07 STATE" in capsys.readouterr().out


def test_it_refuses_once_the_cloud_has_fetched_past_sqlite(sqlite, dynamodb, capsys):
    migrate(sqlite, dynamodb)
    cloud = md.DynamoManifest(TABLE, client=dynamodb)
    cloud.record(
        mf.Record("resultados", date(2026, 11, 3), "u", mf.DRAW, "2026-11-04T00:00:00+00:00")
    )
    capsys.readouterr()
    assert migrate(sqlite, dynamodb) == 2
    out = capsys.readouterr().out
    assert "REFUSED" in out and "newer than SQLite" in out and "not in SQLite" in out
    assert cloud.get("resultados", date(2026, 11, 3))["state"] == mf.DRAW  # untouched


def test_the_interface_check_catches_what_items_alone_would_not(sqlite, dynamodb):
    migrate(sqlite, dynamodb)
    local = mf.SqliteManifest(sqlite, OVERRIDES)
    other = md.DynamoManifest(TABLE, {}, client=dynamodb)  # same items, no overrides
    assert mm.interface_problems(local, other) == ["open_keys() differs"]
    local.close()


def test_a_missing_sqlite_is_refused(tmp_path, dynamodb):
    assert migrate(tmp_path / "nope.sqlite", dynamodb) == 2


class FlakyClient:
    """batch_write_item that leaves everything unprocessed `fails` times."""

    def __init__(self, fails):
        self.fails, self.calls = fails, 0

    def batch_write_item(self, RequestItems):  # noqa: N803 - boto3's name
        self.calls += 1
        if self.calls <= self.fails:
            return {"UnprocessedItems": RequestItems}
        return {"UnprocessedItems": {}}


def test_unprocessed_items_are_retried():
    client = FlakyClient(fails=2)
    mm.write(client, TABLE, [{"pk": "a", "sk": "STATE"}], sleep=lambda s: None)
    assert client.calls == 3


def test_items_that_never_go_through_stop_the_run():
    with pytest.raises(RuntimeError, match="run again"):
        mm.write(FlakyClient(fails=99), TABLE, [{"pk": "a", "sk": "STATE"}], sleep=lambda s: None)
