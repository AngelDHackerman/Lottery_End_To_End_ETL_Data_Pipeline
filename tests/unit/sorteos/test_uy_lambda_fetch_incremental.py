"""The fetch Lambda's incremental mode and its dry run (UY-043.2).

What has to hold: the nightly fetch is ``incremental.fetch_step`` against DynamoDB and S3;
each changed key marks its year in PENDING#silver as it changes, so a run cut short still
hands silver its years; and the dry run asks the site and reports exactly what a real run
would change, while writing nothing anywhere (owner, UY-043.2 a).
"""

from __future__ import annotations

from datetime import date

import boto3
import pytest
from test_uy_backfill import FakeClient  # pytest puts this directory on sys.path
from test_uy_incremental import TODAY, a_week

from sorteos.core import bronze
from sorteos.core import manifest as mf
from sorteos.core import manifest_dynamodb as md
from sorteos.uy import backfill, lambda_fetch, sources

TABLE = "lottery-uy-manifest-test"  # the table the `dynamodb` fixture creates (conftest.py)
BUCKET = "lottery-partitioned-storage-prod"
PREFIX = "uy/raw/"
NOW = "2026-10-29T00:00:00+00:00"


@pytest.fixture
def s3(dynamodb):  # the `dynamodb` fixture keeps moto's mock_aws active
    client = boto3.client("s3", region_name="us-east-1")
    client.create_bucket(Bucket=BUCKET)
    return client


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("MANIFEST_TABLE", TABLE)
    monkeypatch.setenv("BRONZE_BUCKET", BUCKET)
    monkeypatch.setenv("BRONZE_PREFIX", PREFIX)
    monkeypatch.setattr(backfill, "today_in_uruguay", lambda: TODAY)
    monkeypatch.setattr(backfill, "load_overrides", lambda: {})


def run(s3, dynamodb, pages, **event):
    return lambda_fetch.handler(
        {"mode": "incremental", **event}, s3=s3, dynamodb=dynamodb, client=FakeClient(pages)
    )


def objects(s3):
    return sorted(o["Key"] for o in s3.list_objects_v2(Bucket=BUCKET).get("Contents", []))


def table_items(dynamodb):
    return dynamodb.scan(TableName=TABLE)["Items"]


def test_the_nightly_fetch_writes_bronze_the_manifest_and_the_pending_year(s3, dynamodb, env):
    report = run(s3, dynamodb, a_week())
    assert report["window"] == ["2016-07-01", "2016-07-07"]
    assert report["dry_run"] is False and report["years"] == [2016]
    assert ["resultados", "2016-07-06"] in report["changed"]
    assert PREFIX + "country=uy/source=resultados/year=2016/resultados_2016-07-06.html" in (
        objects(s3)
    )
    state = md.DynamoManifest(TABLE, client=dynamodb).get("resultados", date(2016, 7, 6))
    assert state["state"] == mf.DRAW
    assert md.PendingYears(TABLE, dynamodb).read().years == {2016}


def test_a_second_night_with_nothing_new_changes_nothing(s3, dynamodb, env):
    run(s3, dynamodb, a_week())
    rev = md.PendingYears(TABLE, dynamodb).read().rev
    report = run(s3, dynamodb, a_week())
    assert report["changed"] == [] and report["years"] == []
    assert md.PendingYears(TABLE, dynamodb).read().rev == rev  # no year was marked again


def test_a_run_cut_short_has_already_marked_what_it_changed(s3, dynamodb, env):
    """A Lambda timeout mid-run: the keys written before it changed, and the next run will
    see them unchanged. Their year must already be pending when the run dies."""
    pages = a_week()
    pages[sources.RESULTADOS.url(date(2016, 7, 7))] = RuntimeError("the timeout")
    with pytest.raises(RuntimeError, match="timeout"):
        run(s3, dynamodb, pages)
    assert md.PendingYears(TABLE, dynamodb).read().years == {2016}


def test_the_dry_run_reports_what_a_real_run_changes_and_writes_nothing(s3, dynamodb, env):
    dry = run(s3, dynamodb, a_week(), dry_run=True)
    assert objects(s3) == [] and table_items(dynamodb) == []
    assert dry["dry_run"] is True and dry["bronze_not_written"]

    real = run(s3, dynamodb, a_week())
    assert {k: v for k, v in dry.items() if k not in ("dry_run", "bronze_not_written")} == {
        k: v for k, v in real.items() if k != "dry_run"
    }
    assert sorted(PREFIX + k[len("bronze/") :] for k in dry["bronze_not_written"]) == objects(s3)


def test_a_dry_run_after_a_real_one_compares_with_the_bronze_in_s3(s3, dynamodb, env):
    run(s3, dynamodb, a_week())
    before = (objects(s3), len(table_items(dynamodb)))
    dry = run(s3, dynamodb, a_week(), dry_run=True)
    assert dry["changed"] == [] and dry["bronze_not_written"] == []
    assert (objects(s3), len(table_items(dynamodb))) == before


def test_max_requests_stops_the_run(s3, dynamodb, env):
    report = run(s3, dynamodb, a_week(), max_requests=2, dry_run=True)
    assert report["requests"] == 2


# --- the two dry-run stand-ins ------------------------------------------------------------


def test_the_dry_run_manifest_decides_like_the_table_and_writes_nothing(dynamodb):
    """Two identical failures are in the table; the third, recorded dry, closes the key as
    the real record() would: it needs the table's history and its own write."""
    real = md.DynamoManifest(TABLE, client=dynamodb)
    day = date(2026, 10, 1)

    def failure(at):
        return mf.Record("pozos_5_de_oro", day, "u", mf.ERROR, at, http_status=500, detail="x")

    real.record(failure("2026-10-01T00:00:00+00:00"))
    items = len(table_items(dynamodb))
    dry = md.DryRunManifest(TABLE, client=dynamodb)
    assert dry.record(failure("2026-10-02T00:00:00+00:00")) == mf.ERROR
    assert dry.get("pozos_5_de_oro", day)["attempts"] == 2
    assert len(dry.history("pozos_5_de_oro", day, 5)) == 2
    assert dry.history("pozos_5_de_oro", day, 1)[0]["fetched_at"].startswith("2026-10-02")
    assert dry.history("pozos_5_de_oro", day, 0) == []
    assert dry.record(failure("2026-10-03T00:00:00+00:00")) == mf.MISSING
    assert len(table_items(dynamodb)) == items
    assert real.get("pozos_5_de_oro", day)["attempts"] == 1


def test_the_dry_run_store_reads_through_and_keeps_its_writes(s3):
    store = bronze.S3BronzeStore(BUCKET, PREFIX, "uy", client=s3)
    key = store.key("resultados", date(2016, 7, 6), "html")
    store.write(key, b"in s3")
    dry = bronze.DryRunStore(store)
    assert dry.key("resultados", date(2016, 7, 6), "html") == key
    assert dry.read(key) == b"in s3"
    dry.write(key, b"new")
    assert dry.read(key) == b"new" and store.read(key) == b"in s3"
    assert dry.written == {key: b"new"}


def test_a_run_without_max_requests_has_the_default_budget(s3, dynamodb, env, monkeypatch):
    monkeypatch.setattr(lambda_fetch, "DEFAULT_MAX_REQUESTS", 3)
    assert run(s3, dynamodb, a_week(), dry_run=True)["requests"] == 3
