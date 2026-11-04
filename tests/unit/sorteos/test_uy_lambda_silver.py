"""Tests for the silver Lambda's plumbing (UY-042.4.1).

What has to hold: silver is copied down and only changed files go back up; a partition the
local code removes becomes an empty Parquet in S3, never a delete (owner, UY-042.4 1a); a dry
run uploads nothing; and the handler runs the same build_silver functions as `make uy-silver`.
The build itself is tested in test_uy_silver.py.
"""

from __future__ import annotations

import io
import shutil
from datetime import date

import boto3
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from sorteos.core import manifest as mf
from sorteos.core import silver as core_silver
from sorteos.core.manifest_dynamodb import DynamoManifest
from sorteos.uy import build_silver
from sorteos.uy import lambda_silver as ls

BUCKET = "lottery-partitioned-storage-prod"
PREFIX = "uy/silver/"
TABLE = "lottery-uy-manifest-test"  # the table the `dynamodb` fixture creates (conftest.py)
DRAWS_2016 = "draws/country=uy/game=5_de_oro/year=2016/part-0.parquet"
QUARANTINE_2016 = "quarantine/country=uy/year=2016/part-0.parquet"


def parquet(table_name: str, rows: int) -> bytes:
    """A 0-row file of ``table_name``'s schema, or any file with ``rows`` rows: the upload plan
    only reads the row count, and the build is not under test here."""
    if not rows:
        return ls.empty_parquet(f"{table_name}/x")
    buffer = io.BytesIO()
    pq.write_table(pa.table({"x": list(range(rows))}), buffer)
    return buffer.getvalue()


@pytest.fixture
def s3(dynamodb):  # the `dynamodb` fixture keeps moto's mock_aws active
    client = boto3.client("s3", region_name="us-east-1")
    client.create_bucket(Bucket=BUCKET)
    return client


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("SILVER_BUCKET", BUCKET)
    monkeypatch.setenv("SILVER_PREFIX", PREFIX)
    monkeypatch.setenv("BRONZE_PREFIX", "uy/raw/")
    monkeypatch.setenv("MANIFEST_TABLE", TABLE)
    monkeypatch.setattr(ls, "WORK_ROOT", tmp_path / "uy")
    return tmp_path / "uy"


def put(s3, rel, body):
    s3.put_object(Bucket=BUCKET, Key=PREFIX + rel, Body=body)


def get(s3, rel):
    return s3.get_object(Bucket=BUCKET, Key=PREFIX + rel)["Body"].read()


def test_download_copies_every_file_with_its_rows(s3, tmp_path):
    put(s3, DRAWS_2016, parquet("draws", 3))
    put(s3, "draws/", b"")  # a console "folder" is not a file
    found = ls.download_tree(s3, BUCKET, PREFIX, tmp_path / "w")
    assert list(found) == [DRAWS_2016]
    assert found[DRAWS_2016][1] == 3
    assert (tmp_path / "w" / DRAWS_2016).read_bytes() == get(s3, DRAWS_2016)


def test_download_starts_from_an_empty_folder(s3, tmp_path):
    (tmp_path / "w").mkdir()
    (tmp_path / "w" / "left-over").write_text("from a warm container")
    ls.download_tree(s3, BUCKET, PREFIX, tmp_path / "w")
    assert not (tmp_path / "w" / "left-over").exists()


def test_only_new_and_changed_files_are_put_and_gone_ones_emptied():
    before = {"a": ("1", 5), "b": ("2", 5), "gone": ("3", 4), "gone-empty": ("4", 0)}
    after = {"a": "1", "b": "changed", "new": "5"}
    assert ls.plan_upload(before, after) == (["b", "new"], ["gone"])


def test_an_emptied_partition_is_a_0_row_file_of_its_table():
    data = ls.empty_parquet(QUARANTINE_2016)
    table = pq.read_table(io.BytesIO(data))
    assert table.num_rows == 0
    assert table.schema == core_silver.QUARANTINE.file_schema


def fake_rebuild(write):
    """A build_silver.rebuild that writes files with ``write(root)`` and counts one year."""

    def rebuild(manifest, bronze, out, years, run):
        write(out)
        return [build_silver.YearCount(year=y, draws=10, seconds=1.25) for y in years]

    return rebuild


def test_a_year_uploads_what_it_wrote_and_empties_what_it_removed(s3, env, monkeypatch):
    put(s3, DRAWS_2016, parquet("draws", 3))
    put(s3, QUARANTINE_2016, parquet("quarantine", 2))
    new_draws = parquet("draws", 4)

    def write(root):
        (root / DRAWS_2016).write_bytes(new_draws)
        shutil.rmtree(root / "quarantine/country=uy/year=2016")  # what core/silver.py does

    monkeypatch.setattr(build_silver, "rebuild", fake_rebuild(write))
    report = ls.handler({"years": [2016]}, s3=s3)
    assert report["put"] == [DRAWS_2016] and report["emptied"] == [QUARANTINE_2016]
    assert report["years"] == [{"year": 2016, "draws": 10, "quarantine": 0, "seconds": 1.2}]
    assert get(s3, DRAWS_2016) == new_draws
    assert pq.read_table(io.BytesIO(get(s3, QUARANTINE_2016))).num_rows == 0
    assert report["ok"] is True
    assert set(report["timings"]) == {"silver_down", "manifest", "bronze_down", "build", "upload"}
    assert report["bronze"] == {"files": 0, "mb": 0.0}  # the test table is empty


def test_a_dry_run_uploads_nothing(s3, env, monkeypatch):
    put(s3, DRAWS_2016, parquet("draws", 3))
    original = get(s3, DRAWS_2016)
    monkeypatch.setattr(
        build_silver, "rebuild", fake_rebuild(lambda root: (root / DRAWS_2016).write_bytes(b"x"))
    )
    report = ls.handler({"years": [2016], "dry_run": True}, s3=s3)
    assert report["put"] == [DRAWS_2016] and report["dry_run"] is True
    assert get(s3, DRAWS_2016) == original
    assert "upload" not in report["timings"]


@pytest.mark.parametrize("gap_rows, ok", [([{"g": 1}], True), (None, False)])
def test_finalize_rewrites_the_gaps_and_fails_on_quarantine(s3, env, monkeypatch, gap_rows, ok):
    def detect_gaps(out, run, today):
        return build_silver.GapReport(rows=gap_rows, quarantine=0 if ok else 3)

    monkeypatch.setattr(build_silver, "detect_gaps", detect_gaps)
    monkeypatch.setattr(build_silver, "rebuild", lambda *a: pytest.fail("no years were given"))
    report = ls.handler({"finalize": True}, s3=s3)
    assert report["ok"] is ok
    assert report["gaps"] == {"rows": 1 if ok else None, "quarantine": 0 if ok else 3}


@pytest.mark.parametrize(
    "event, problem",
    [
        ({}, "nothing to do"),
        ({"years": [2005]}, "years must be"),
        ({"years": "2016"}, "years must be"),
        ({"years": [True]}, "years must be"),
    ],
)
def test_the_handler_refuses_a_bad_event(event, problem):
    with pytest.raises(ValueError, match=problem):
        ls.handler(event)


# --- the snapshot and the bronze it needs (owner, UY-042.4.1 1a) -------------------------

NOW = "2026-10-31T18:14:06+00:00"


def record(m, source, day, state=mf.DRAW, key=True):
    bronze_key = f"bronze/country=uy/source={source}/year={day[:4]}/{source}_{day}.html"
    m.record(
        mf.Record(
            source,
            date.fromisoformat(day),
            "u",
            state,
            NOW,
            content=b"x",
            bronze_key=bronze_key if key else None,
        )
    )
    return bronze_key


def test_the_bronze_needed_is_the_years_pages_and_every_pozos_pdf(dynamodb):
    m = DynamoManifest(TABLE, client=dynamodb)
    page_2016 = record(m, "resultados", "2016-07-06")
    extract_2016 = record(m, "extracto_5_de_oro", "2016-07-06")
    record(m, "resultados", "2017-01-04")  # another year
    record(m, "resultados", "2016-07-07", state=mf.NO_DRAW)  # nothing in bronze
    record(m, "resultados", "2016-07-08", key=False)  # a draw row without a file
    pozos_2016 = record(m, "pozos_5_de_oro", "2016-07-06")
    pozos_2025 = record(m, "pozos_5_de_oro", "2025-03-02")  # any year: the series needs it
    keys = ls.needed_bronze(m.snapshot(), [2016])
    assert keys == sorted([page_2016, extract_2016, pozos_2016, pozos_2025])


def test_bronze_lands_where_the_local_store_reads_it(s3, tmp_path):
    from sorteos.core.bronze import BronzeStore

    key = "bronze/country=uy/source=resultados/year=2016/resultados_2016-07-06.html"
    s3.put_object(Bucket=BUCKET, Key="uy/raw/" + key[len("bronze/") :], Body=b"<html/>")
    size = ls.download_bronze(s3, BUCKET, "uy/raw/", [key], tmp_path)
    assert size == len(b"<html/>")
    assert BronzeStore(tmp_path, "uy").read(key) == b"<html/>"


def test_a_missing_or_foreign_bronze_key_fails_the_run(s3, tmp_path):
    with pytest.raises(ValueError, match="not a bronze key"):
        ls.download_bronze(s3, BUCKET, "uy/raw/", ["silver/x.parquet"], tmp_path)
    with pytest.raises(s3.exceptions.NoSuchKey):
        ls.download_bronze(s3, BUCKET, "uy/raw/", ["bronze/country=uy/missing.html"], tmp_path)


def test_a_warm_container_starts_from_an_empty_work_root(s3, env, monkeypatch):
    (env / "bronze").mkdir(parents=True)
    (env / "bronze" / "stale.html").write_text("from the last invocation")
    monkeypatch.setattr(build_silver, "rebuild", fake_rebuild(lambda root: None))
    ls.handler({"years": [2016], "dry_run": True}, s3=s3)
    assert not (env / "bronze" / "stale.html").exists()
