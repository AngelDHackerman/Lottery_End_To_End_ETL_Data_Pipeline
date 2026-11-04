"""Tests for the fetch Lambda's probe (UY-042.3; D26) and the S3 bronze store it will write to.

What has to hold: the probe asks for the newest draw of each source and nothing else, says per
key whether the site answered and served the same bytes, never writes, and is built on the
privacy-guarded client. And S3BronzeStore puts a bronze key exactly where P15 says.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime

import boto3
import pytest
from moto import mock_aws

from sorteos.core import bronze
from sorteos.core import manifest as mf
from sorteos.core.http_client import FetchError, FetchResult
from sorteos.core.manifest_dynamodb import DynamoManifest
from sorteos.uy import lambda_fetch, privacy

TABLE = "lottery-uy-manifest-test"  # the table the `dynamodb` fixture creates (conftest.py)
NOW = "2026-10-31T18:14:06+00:00"
PAGE = b"<html>resultados</html>"
PDF = b"%PDF-1.4 pozos"


class FakeClient:
    """Answers each URL from a dict: bytes (200), an int status, or a FetchError."""

    def __init__(self, answers):
        self.answers, self.asked = answers, []

    def get(self, url):
        self.asked.append(url)
        answer = self.answers[url]
        if isinstance(answer, Exception):
            raise answer
        status, content = (answer, b"") if isinstance(answer, int) else (200, answer)
        return FetchResult(url, url, status, {}, content, datetime.now(UTC), 0.1)


@pytest.fixture
def manifest(dynamodb):
    m = DynamoManifest(TABLE, client=dynamodb)
    for day, content in ((date(2026, 10, 29), b"older"), (date(2026, 10, 30), PAGE)):
        m.record(mf.Record("resultados", day, f"u/r/{day}", mf.DRAW, NOW, content=content))
    m.record(mf.Record("resultados", date(2026, 10, 31), "u/r/31", mf.NO_DRAW, NOW))
    m.record(mf.Record("pozos_5_de_oro", date(2026, 10, 26), "u/p", mf.DRAW, NOW, content=PDF))
    return m


def count_items(client):
    return client.scan(TableName=TABLE, Select="COUNT")["Count"]


def test_the_probe_asks_for_the_newest_draw_of_each_source(manifest, dynamodb):
    client = FakeClient({"u/r/2026-10-30": PAGE, "u/p": PDF})
    before = count_items(dynamodb)
    report = lambda_fetch.probe(manifest, client, ["resultados", "pozos_5_de_oro"])
    assert client.asked == ["u/r/2026-10-30", "u/p"]  # not the older draw, not the no_draw day
    assert report["ok"] is True and report["same_bytes"] == 2 and report["keys"] == 2
    assert report["results"][0] | {"seconds": 0} == {
        "source": "resultados",
        "draw_date": "2026-10-30",
        "url": "u/r/2026-10-30",
        "status": 200,
        "bytes": len(PAGE),
        "same_bytes": True,
        "seconds": 0,
    }
    assert count_items(dynamodb) == before  # writes nothing


def test_other_bytes_are_reported_but_do_not_fail(manifest):
    client = FakeClient({"u/r/2026-10-30": b"<html>changed</html>", "u/p": PDF})
    report = lambda_fetch.probe(manifest, client, ["resultados", "pozos_5_de_oro"])
    assert report["ok"] is True and report["same_bytes"] == 1
    assert report["results"][0]["same_bytes"] is False


@pytest.mark.parametrize(
    "answer", [403, FetchError("HTTP 503 after 2 retries")], ids=["403", "no answer"]
)
def test_a_key_the_site_does_not_serve_fails_the_probe(manifest, answer):
    client = FakeClient({"u/r/2026-10-30": answer, "u/p": PDF})
    report = lambda_fetch.probe(manifest, client, ["resultados", "pozos_5_de_oro"])
    assert report["ok"] is False
    first = report["results"][0]
    assert first.get("status") == 403 or "503" in first.get("error", "")


def test_a_source_with_no_draw_is_reported_without_a_request(manifest):
    client = FakeClient({})
    report = lambda_fetch.probe(manifest, client, ["extracto_pdf_5_de_oro"])
    assert client.asked == []
    assert report["ok"] is False
    assert report["results"] == [
        {"source": "extracto_pdf_5_de_oro", "error": "no draw in the manifest"}
    ]


def test_the_handler_uses_the_guarded_client_and_the_table_from_the_env(
    manifest, dynamodb, monkeypatch
):
    made = {}

    def fake_polite_client(**kwargs):
        made.update(kwargs)
        return FakeClient({"u/r/2026-10-30": PAGE})

    monkeypatch.setenv("MANIFEST_TABLE", TABLE)
    monkeypatch.setattr(privacy, "polite_client", fake_polite_client)
    monkeypatch.setattr(lambda_fetch, "DynamoManifest", lambda table, overrides: manifest)
    report = lambda_fetch.handler({"mode": "probe", "sources": ["resultados"]})
    assert report["ok"] is True
    assert made == {"max_retries": 2, "backoff_cap": 10.0}


def test_the_real_client_keeps_the_privacy_guard():
    client = privacy.polite_client(
        max_retries=lambda_fetch.PROBE_RETRIES, backoff_cap=lambda_fetch.PROBE_BACKOFF_CAP
    )
    assert "DET_INVALIDAS" in client.blocklist


@pytest.mark.parametrize(
    "event, problem",
    [({"mode": "fetch"}, "only 'probe'"), ({"sources": ["kini"]}, "unknown sources")],
)
def test_the_handler_refuses_what_is_not_a_probe_yet(event, problem):
    with pytest.raises(ValueError, match=problem):
        lambda_fetch.handler(event)


# --- S3BronzeStore -------------------------------------------------------------------------

BUCKET = "lottery-partitioned-storage-prod"


@pytest.fixture
def s3():
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield client


def test_a_bronze_key_lands_where_p15_says(s3, tmp_path):
    store = bronze.S3BronzeStore(BUCKET, "uy/raw/", "uy", client=s3)
    local = bronze.BronzeStore(tmp_path, "uy")
    day = date(2016, 7, 6)
    key = store.key("resultados", day, "html")
    assert key == local.key("resultados", day, "html")
    store.write(key, PAGE)
    expected = "uy/raw/country=uy/source=resultados/year=2016/resultados_2016-07-06.html"
    body = s3.get_object(Bucket=BUCKET, Key=expected)["Body"].read()
    assert body == PAGE
    assert store.read(key) == PAGE
    assert hashlib.sha256(store.read(key)).hexdigest() == hashlib.sha256(PAGE).hexdigest()


def test_the_store_refuses_a_key_outside_bronze_and_a_bare_prefix(s3):
    store = bronze.S3BronzeStore(BUCKET, "uy/raw/", "uy", client=s3)
    with pytest.raises(ValueError, match="not a bronze key"):
        store.write("silver/draws/x.parquet", b"x")
    with pytest.raises(ValueError, match="must end with '/'"):
        bronze.S3BronzeStore(BUCKET, "uy/raw", "uy", client=s3)
