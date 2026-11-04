"""The silver Lambda (UY-042.4.1; DESIGN.md D17, D18, D29): local silver code, cloud inputs.

    {"years": [2016]}                       # rebuild these years (and the reference tables)
    {"finalize": true}                      # rewrite draw_gaps from the silver in S3
    {"years": [2016], "dry_run": true}      # build, measure, report; upload nothing

**How.** It makes ``/tmp/uy`` look like ``data/uy`` and then runs the very functions
``make uy-silver`` runs (``build_silver.rebuild`` and ``detect_gaps``), so ``core/silver.py``
and the parsers never know they are in the cloud and local and cloud silver come out of the
same code, which is what UY-042.4.2 reconciles:

1. ``uy/silver/`` is copied to ``/tmp/uy/silver`` (~5 MB);
2. the manifest is read with ONE Scan into a read-only snapshot (owner, UY-042.4.1 1a). The
   silver code asks about every day since 2006, twice per day: ~10,000 GetItems per run
   against DynamoDB, microseconds each against SQLite;
3. the bronze those years read (their pages, plus every pozos PDF for the draw-number series)
   is downloaded IN PARALLEL to ``/tmp/uy/bronze``, and the plain local ``BronzeStore`` reads
   it from there; ``_page`` still checks each page's SHA-256 against the manifest;
4. after the build, only the files whose bytes changed go back to S3.

**No deletes (owner, UY-042.4 1a).** Locally, a partition that no longer has rows is removed
(``shutil.rmtree``). In S3 that would be a DeleteObject, which the bucket's Deny refuses to
everyone but root and the gold purge. So the cloud writes an empty Parquet (the table's schema,
0 rows) where the partition was: Athena, GX and pyarrow read 0 rows, as from no file, and the
versioned bucket keeps the previous object.

**The measurement (D18).** Each year reports its build + write seconds, as ``make uy-silver``
does; ``timings`` adds each step around it: silver down, the manifest Scan, the bronze
download, the whole build (with the draw-number series) and the upload.

Years run in the order given and each one uploads only what it wrote, so separate invocations
for separate years do not undo each other. ``finalize`` reads every year's draws, so it runs
after the years it should see.
"""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from sorteos.core import manifest as mf
from sorteos.core import silver as core_silver
from sorteos.core.bronze import BRONZE_ROOT, BronzeStore
from sorteos.core.manifest_dynamodb import DynamoManifest, ManifestSnapshot
from sorteos.uy import backfill, build_silver
from sorteos.uy.parsers import pozos_pdf
from sorteos.uy.sources import COUNTRY

# /tmp is the only writable path in Lambda; the handler empties it at the start of each run.
WORK_ROOT = Path("/tmp/uy")  # nosec B108
WORKERS = 32  # parallel S3 downloads: the run is bound by latency, not bandwidth
FIRST_YEAR, LAST_YEAR = 2006, 2100

File = tuple[str, int]  # (sha256, rows) of one Parquet file


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _rows(content: bytes) -> int:
    return pq.read_metadata(io.BytesIO(content)).num_rows


def download_many(client, bucket: str, pairs: Iterable[tuple[str, Path]]) -> int:
    """Download each (key, path) in parallel; return the bytes. Any failure raises."""

    def one(pair: tuple[str, Path]) -> int:
        key, path = pair
        content = client.get_object(Bucket=bucket, Key=key)["Body"].read()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return len(content)

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        return sum(pool.map(one, list(pairs)))


def download_tree(client, bucket: str, prefix: str, root: Path) -> dict[str, File]:
    """Copy every object under ``prefix`` to ``root``; return what was copied."""
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    rels = [
        obj["Key"][len(prefix) :]
        for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix)
        for obj in page.get("Contents", [])
        if obj["Key"][len(prefix) :] and not obj["Key"].endswith("/")
    ]
    download_many(client, bucket, ((prefix + rel, root / rel) for rel in rels))
    found: dict[str, File] = {}
    for rel in rels:
        content = (root / rel).read_bytes()
        found[rel] = (_sha(content), _rows(content))
    return found


def needed_bronze(manifest: ManifestSnapshot, years: Iterable[int]) -> list[str]:
    """The bronze keys a build of ``years`` reads: every stored ``draw`` page of those years,
    and every pozos PDF, which the draw-number series reads whatever the years (UY-025.3).
    A superset is harmless; a key missing here would fail the build when ``_page`` reads it."""
    wanted = {str(y) for y in years}
    return sorted(
        row["bronze_key"]
        for row in manifest.rows()
        if row["state"] == mf.DRAW
        and row["bronze_key"]
        and (row["source"] == pozos_pdf.SOURCE or row["draw_date"][:4] in wanted)
    )


def download_bronze(client, bucket: str, prefix: str, keys: list[str], root: Path) -> int:
    """Put each bronze key at ``root / key``, where a local ``BronzeStore(root)`` reads it."""
    for key in keys:
        if not key.startswith(BRONZE_ROOT):
            raise ValueError(f"not a bronze key: {key!r}")
    return download_many(client, bucket, ((prefix + k[len(BRONZE_ROOT) :], root / k) for k in keys))


def file_hashes(root: Path) -> dict[str, str]:
    """sha256 of every file under ``root``, by its path relative to it."""
    return {
        p.relative_to(root).as_posix(): _sha(p.read_bytes())
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


def empty_parquet(rel: str) -> bytes:
    """A 0-row file with the schema of the table ``rel`` belongs to (its first path part)."""
    table = core_silver.TABLES[rel.split("/", 1)[0]]
    buffer = io.BytesIO()
    pq.write_table(pa.Table.from_pylist([], schema=table.file_schema), buffer)
    return buffer.getvalue()


def plan_upload(before: dict[str, File], after: dict[str, str]) -> tuple[list[str], list[str]]:
    """The files to put (new or changed bytes) and the ones to empty (gone, and not empty yet)."""
    put = sorted(rel for rel, sha in after.items() if before.get(rel, ("", 0))[0] != sha)
    empty = sorted(rel for rel, (_, rows) in before.items() if rel not in after and rows > 0)
    return put, empty


def upload(client, bucket: str, prefix: str, root: Path, put: list[str], empty: list[str]) -> None:
    for rel in put:
        client.put_object(Bucket=bucket, Key=prefix + rel, Body=(root / rel).read_bytes())
    for rel in empty:
        client.put_object(Bucket=bucket, Key=prefix + rel, Body=empty_parquet(rel))


def _years(event: dict) -> list[int]:
    years = event.get("years") or []
    if not isinstance(years, list) or not all(
        isinstance(y, int) and not isinstance(y, bool) and FIRST_YEAR <= y <= LAST_YEAR
        for y in years
    ):
        raise ValueError(f"years must be a list of years {FIRST_YEAR}–{LAST_YEAR}: {years!r}")
    return years


def handler(event: dict | None, context: Any = None, s3=None, dynamodb=None) -> dict[str, Any]:
    event = event or {}
    years = _years(event)
    finalize = bool(event.get("finalize"))
    dry_run = bool(event.get("dry_run"))
    if not years and not finalize:
        raise ValueError('nothing to do: give "years", "finalize" or both')
    if s3 is None:  # pragma: no cover - the tests pass moto clients
        import boto3
        from botocore.config import Config

        # One pooled connection per download thread; the default pool of 10 makes the other
        # 22 threads open and drop a connection per object.
        s3 = boto3.client("s3", config=Config(max_pool_connections=WORKERS))
    bucket = os.environ["SILVER_BUCKET"]
    silver_prefix = os.environ["SILVER_PREFIX"]

    silver_dir = WORK_ROOT / "silver"
    if WORK_ROOT.exists():  # a warm container keeps /tmp: start from nothing
        shutil.rmtree(WORK_ROOT)

    timings: dict[str, float] = {}
    started = time.perf_counter()
    before = download_tree(s3, bucket, silver_prefix, silver_dir)
    timings["silver_down"] = time.perf_counter() - started

    run = build_silver.new_run("silver")
    report: dict[str, Any] = {"run_id": run.run_id, "years": [], "dry_run": dry_run}

    if years:
        started = time.perf_counter()
        table = DynamoManifest(os.environ["MANIFEST_TABLE"], backfill.load_overrides(), dynamodb)
        manifest = table.snapshot()
        timings["manifest"] = time.perf_counter() - started

        started = time.perf_counter()
        keys = needed_bronze(manifest, years)
        size = download_bronze(s3, bucket, os.environ["BRONZE_PREFIX"], keys, WORK_ROOT)
        timings["bronze_down"] = time.perf_counter() - started
        report["bronze"] = {"files": len(keys), "mb": round(size / 1e6, 1)}

        started = time.perf_counter()
        bronze = BronzeStore(WORK_ROOT, COUNTRY)
        counts = build_silver.rebuild(manifest, bronze, silver_dir, years, run)
        timings["build"] = time.perf_counter() - started
        report["years"] = [
            {
                "year": c.year,
                "draws": c.draws,
                "quarantine": c.quarantine,
                "seconds": round(c.seconds, 1),
            }
            for c in counts
        ]
    if finalize:
        started = time.perf_counter()
        gaps = build_silver.detect_gaps(silver_dir, run, backfill.today_in_uruguay())
        timings["gaps"] = time.perf_counter() - started
        report["gaps"] = {
            "rows": None if gaps.rows is None else len(gaps.rows),
            "quarantine": gaps.quarantine,
        }

    put, empty = plan_upload(before, file_hashes(silver_dir))
    if not dry_run:
        started = time.perf_counter()
        upload(s3, bucket, silver_prefix, silver_dir, put, empty)
        timings["upload"] = time.perf_counter() - started
    report |= {
        "put": put,
        "emptied": empty,
        "timings": {k: round(v, 1) for k, v in timings.items()},
        "ok": "gaps" not in report or report["gaps"]["rows"] is not None,
    }
    return report
