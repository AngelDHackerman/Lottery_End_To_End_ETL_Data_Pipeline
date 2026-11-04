"""Tests for the bronze upload check (UY-042.1).

What has to hold: a file counts as uploaded only when an object with the same key, size and
MD5 is there; a missing or changed file fails the check; and objects outside ``uy/raw/`` (all
of Santa Lucía's data is in the same bucket) are never counted.
"""

from __future__ import annotations

import boto3
import pytest
from moto import mock_aws

from sorteos.uy import bronze_sync as bs

BUCKET = "lottery-partitioned-storage-prod"
PAGE = "country=uy/source=resultados/year=2016/resultados_2016-01-03.html"
PDF = "country=uy/source=pozos_5_de_oro/year=2016/pozos_5_de_oro_2016-06-01.pdf"


@pytest.fixture
def bronze(tmp_path):
    root = tmp_path / "bronze"
    for key, body in ((PAGE, b"<html>sorteo</html>"), (PDF, b"%PDF-1.4 pozos")):
        path = root / key
        path.parent.mkdir(parents=True)
        path.write_bytes(body)
    return root


@pytest.fixture
def s3():
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=BUCKET)
        yield client


def upload(client, root, keys):
    for key in keys:
        client.put_object(
            Bucket=BUCKET, Key=bs.DEFAULT_PREFIX + key, Body=(root / key).read_bytes()
        )


def run(root, client):
    return bs.main(["--root", str(root), "--bucket", BUCKET], client=client)


def test_local_inventory_keys_are_relative_and_skip_unfinished_writes(bronze):
    (bronze / (PAGE + ".tmp")).write_bytes(b"half a page")
    inventory = bs.local_inventory(bronze)
    assert sorted(inventory) == sorted([PAGE, PDF])
    assert inventory[PAGE].size == len(b"<html>sorteo</html>")


def test_everything_uploaded_passes(bronze, s3, capsys):
    upload(s3, bronze, [PAGE, PDF])
    assert run(bronze, s3) == 0
    assert "OK: every local bronze file is in S3" in capsys.readouterr().out


def test_before_the_upload_it_is_the_dry_run(bronze, s3, capsys):
    assert run(bronze, s3) == 1
    out = capsys.readouterr().out
    assert "missing in S3:          2" in out
    assert PAGE in out


def test_same_size_other_content_fails(bronze, s3):
    upload(s3, bronze, [PDF])
    s3.put_object(Bucket=BUCKET, Key=bs.DEFAULT_PREFIX + PAGE, Body=b"<html>SORTEO</html>")
    result = bs.compare(bs.local_inventory(bronze), bs.s3_inventory(s3, BUCKET, bs.DEFAULT_PREFIX))
    assert result.different == [PAGE]
    assert run(bronze, s3) == 1


def test_objects_only_in_s3_are_reported_not_failed(bronze, s3, capsys):
    upload(s3, bronze, [PAGE, PDF])
    later = "country=uy/source=resultados/year=2026/resultados_2026-11-05.html"
    s3.put_object(Bucket=BUCKET, Key=bs.DEFAULT_PREFIX + later, Body=b"from the Lambda")
    assert run(bronze, s3) == 0
    assert later in capsys.readouterr().out


def test_santa_lucia_and_other_uy_layers_are_not_counted(bronze, s3):
    upload(s3, bronze, [PAGE, PDF])
    s3.put_object(Bucket=BUCKET, Key="raw/sorteo_1.txt", Body=b"santa lucia")
    s3.put_object(Bucket=BUCKET, Key="uy/silver/draws/part.parquet", Body=b"silver")
    # A console "folder" and an unfinished write are not bronze either.
    s3.put_object(Bucket=BUCKET, Key=bs.DEFAULT_PREFIX + "country=uy/", Body=b"")
    s3.put_object(Bucket=BUCKET, Key=bs.DEFAULT_PREFIX + PAGE + ".tmp", Body=b"half")
    remote = bs.s3_inventory(s3, BUCKET, bs.DEFAULT_PREFIX)
    assert sorted(remote) == sorted([PAGE, PDF])


def test_a_multipart_etag_is_compared_by_size_only():
    local = {PAGE: bs.Entry(10, "0" * 32)}
    assert bs.compare(local, {PAGE: bs.Entry(10, None)}).size_only == [PAGE]
    assert bs.compare(local, {PAGE: bs.Entry(11, None)}).different == [PAGE]


def test_a_root_without_country_is_refused(tmp_path, s3):
    assert run(tmp_path, s3) == 2
