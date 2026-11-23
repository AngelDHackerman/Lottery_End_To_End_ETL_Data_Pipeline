"""Tests for UY-042.4.2: the cloud backfill of silver and its row-by-row reconciliation.

What has to hold: the backfill invokes one year at a time, in order, then finalize, and stops
at the first error; the reconciliation matches rows by key, ignores only ingested_at and
run_id, and reports every row that is missing, extra, different or repeated.
"""

from __future__ import annotations

import io
import json
from datetime import date, datetime
from types import SimpleNamespace

import boto3

from sorteos.core import manifest as mf
from sorteos.core.manifest_dynamodb import DynamoManifest
from sorteos.uy import build_silver
from sorteos.uy import silver_backfill as sb
from sorteos.uy import silver_compare as sc

TABLE = "lottery-uy-manifest-test"  # the table the `dynamodb` fixture creates (conftest.py)


# --- the backfill ---------------------------------------------------------------------------


class FakeLambda:
    """Answers like the silver Lambda; ``fail_on`` makes that payload a function error."""

    def __init__(self, fail_on=None, gaps_rows=12):
        self.payloads, self.fail_on, self.gaps_rows = [], fail_on, gaps_rows

    def invoke(self, FunctionName, Payload):  # noqa: N803 - boto3's names
        payload = json.loads(Payload)
        self.payloads.append(payload)
        if payload == self.fail_on:
            body = {"errorMessage": "boom", "errorType": "ValueError"}
            return {"FunctionError": "Unhandled", "Payload": io.BytesIO(json.dumps(body).encode())}
        if payload.get("finalize"):
            ok = self.gaps_rows is not None
            body = {"gaps": {"rows": self.gaps_rows, "quarantine": 0 if ok else 2}, "ok": ok}
        else:
            (year,) = payload["years"]
            body = {
                "years": [{"year": year, "draws": 600, "quarantine": 0, "seconds": 20.0}],
                "timings": {"build": 40.0},
            }
        return {"Payload": io.BytesIO(json.dumps(body).encode())}


def test_the_backfill_goes_year_by_year_then_finalizes(tmp_path):
    client, lines = FakeLambda(), []
    summary = sb.run(client, "fn", [2010, 2011], tmp_path, log=lines.append)
    assert client.payloads == [{"years": [2010]}, {"years": [2011]}, {"finalize": True}]
    assert summary["draws"] == 1200 and summary["ok"] is True and summary["gaps"]["rows"] == 12
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "silver-2010.json",
        "silver-2011.json",
        "silver-backfill.json",
        "silver-finalize.json",
    ]
    assert lines[0].startswith("2010   600 draws") and "draw_gaps 12 rows" in lines[-1]


def test_the_first_error_stops_the_backfill(tmp_path):
    client = FakeLambda(fail_on={"years": [2010]})
    assert (
        sb.main(
            ["--function", "fn", "--table", TABLE, "--years", "2010-2012", "--out", str(tmp_path)],
            lambda_client=client,
        )
        == 2
    )
    assert client.payloads == [{"years": [2010]}]  # 2011, 2012 and finalize never run


def test_quarantine_fails_the_backfill(tmp_path):
    client = FakeLambda(gaps_rows=None)
    assert (
        sb.main(
            ["--function", "fn", "--table", TABLE, "--years", "2010", "--out", str(tmp_path)],
            lambda_client=client,
        )
        == 1
    )


def test_the_years_default_to_the_manifests_span(tmp_path, dynamodb):
    m = DynamoManifest(TABLE, client=dynamodb)
    for day in (date(2010, 3, 3), date(2012, 5, 5)):
        m.record(mf.Record("resultados", day, "u", mf.DRAW, "2026-11-04T00:00:00+00:00"))
    client = FakeLambda()
    code = sb.main(
        ["--function", "fn", "--table", TABLE, "--out", str(tmp_path)],
        lambda_client=client,
        dynamodb=dynamodb,
    )
    assert code == 0
    assert [p.get("years") for p in client.payloads] == [[2010], [2011], [2012], None]


# --- the reconciliation --------------------------------------------------------------------

T = SimpleNamespace(name="t", key=("country", "games"))
NOW = datetime(2026, 11, 4, 20, 0)


def row(games, value, run="uy-silver-a", at=NOW):
    return {"country": "uy", "games": games, "value": value, "run_id": run, "ingested_at": at}


def test_runs_differ_but_rows_match():
    local = [row(["5_de_oro"], 1, "uy-reconcile-x"), row(["quiniela"], 2)]
    cloud = [row(["quiniela"], 2, "uy-silver-y", datetime(2026, 1, 1)), row(["5_de_oro"], 1)]
    result = sc.compare_table(T, local, cloud)
    assert result.ok and result.local_digest == result.cloud_digest and result.local == 2


def test_every_kind_of_difference_is_reported():
    local = [row(["a"], 1), row(["b"], 2), row(["c"], 3), row(["c"], 3)]
    cloud = [row(["a"], 1), row(["b"], 20), row(["d"], 4)]
    result = sc.compare_table(T, local, cloud)
    assert not result.ok
    assert result.missing == [("uy", ("c",))]
    assert result.extra == [("uy", ("d",))]
    assert result.different == [(("uy", ("b",)), ["value"])]
    assert result.duplicates == ["local: ('uy', ('c',))"]
    text = sc.render([result])
    assert "DIFFERS" in text and "only local" in text and "only in the cloud" in text
    assert text.endswith("FAIL")


def test_two_empty_silvers_match(tmp_path):
    results = sc.compare(tmp_path / "a", tmp_path / "b")
    assert len(results) == 7 and all(r.ok for r in results)
    assert sc.render(results).endswith("(ingested_at and run_id aside).")


def test_main_builds_locally_downloads_the_cloud_and_compares(tmp_path, monkeypatch, dynamodb):
    (tmp_path / "manifest.sqlite").touch()
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="uy-bucket")
    built = []
    monkeypatch.setattr(sc, "build_local", lambda root, out: built.append((root, out)))
    assert sc.main(["--root", str(tmp_path), "--bucket", "uy-bucket"], s3=s3) == 0
    assert built and built[0][0] == tmp_path
    monkeypatch.setattr(sc, "compare", lambda local, cloud: [sc.TableResult("t", missing=[("k",)])])
    assert sc.main(["--root", str(tmp_path), "--bucket", "uy-bucket"], s3=s3) == 1


def test_main_refuses_a_root_without_a_manifest(tmp_path):
    assert sc.main(["--root", str(tmp_path), "--bucket", "uy-bucket"]) == 2


def test_build_local_is_make_uy_silver(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        build_silver,
        "rebuild",
        lambda manifest, bronze, out, years, run: calls.append(("rebuild", out, years)),
    )
    monkeypatch.setattr(
        build_silver, "detect_gaps", lambda out, run, today: calls.append(("gaps", out))
    )
    sc.build_local(tmp_path, tmp_path / "out")  # an empty manifest: no years
    assert calls == [("rebuild", tmp_path / "out", []), ("gaps", tmp_path / "out")]
