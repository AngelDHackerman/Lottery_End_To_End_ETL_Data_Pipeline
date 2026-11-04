"""Rebuild all of UY silver in the cloud: one silver Lambda invocation per year (UY-042.4.2).

    python -m sorteos.uy.silver_backfill --function lottery-uy-silver-prod \\
        --table lottery-uy-manifest-prod [--years 2006-2026] [--out dist/uy/backfill]

**One year at a time, in order (owner, UY-042.4.2 1a).** Each year is a synchronous invoke of
``{"years": [year]}``; after the last one, ``{"finalize": true}`` rewrites ``draw_gaps`` from
everything the years wrote. The first error stops the run: what is in S3 then is every year
before it, and running again redoes them all (each year replaces its own partitions, D17).
In parallel it would take a quarter of the time, but use 4 of the account's 10 concurrent
executions, which Santa Lucía shares; the parallel Map belongs to Step Functions (UY-043).

The years default to the manifest's own span (``build_silver.all_years``), read from DynamoDB.
Each report is kept as ``<out>/silver-<year>.json`` and the summary as ``silver-backfill.json``.
The exit code is 0 when ``finalize`` wrote ``draw_gaps``, 1 when it did not (silver has rows in
quarantine) and 2 when an invocation failed.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from sorteos.core.manifest_dynamodb import DynamoManifest
from sorteos.uy import backfill, build_silver


class CloudSilverError(RuntimeError):
    pass


def invoke(client, function: str, payload: dict) -> dict[str, Any]:
    """One synchronous invoke; a function error becomes CloudSilverError with its message."""
    response = client.invoke(FunctionName=function, Payload=json.dumps(payload).encode())
    body = json.loads(response["Payload"].read() or b"null")
    if response.get("FunctionError"):
        detail = body if not isinstance(body, dict) else body.get("errorMessage", body)
        raise CloudSilverError(f"{payload}: {response['FunctionError']}: {detail}")
    return body


def run(client, function: str, years: list[int], out: Path, log=print) -> dict[str, Any]:
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for year in years:
        started = time.monotonic()
        report = invoke(client, function, {"years": [year]})
        wall = time.monotonic() - started
        (out / f"silver-{year}.json").write_text(json.dumps(report, indent=2))
        (counts,) = report["years"]
        rows.append({**counts, "wall": round(wall, 1), "timings": report["timings"]})
        log(
            f"{year}  {counts['draws']:>4} draws  {counts['quarantine']:>3} quarantine  "
            f"year {counts['seconds']:>5.1f} s  invocation {wall:>5.1f} s"
        )
    started = time.monotonic()
    final = invoke(client, function, {"finalize": True})
    (out / "silver-finalize.json").write_text(json.dumps(final, indent=2))
    summary = {
        "years": rows,
        "draws": sum(r["draws"] for r in rows),
        "quarantine": sum(r["quarantine"] for r in rows),
        "seconds": round(sum(r["wall"] for r in rows) + time.monotonic() - started, 1),
        "slowest": max(rows, key=lambda r: r["wall"])["year"] if rows else None,
        "gaps": final["gaps"],
        "ok": final["ok"],
    }
    (out / "silver-backfill.json").write_text(json.dumps(summary, indent=2))
    log(
        f"total {summary['draws']:,} draws, {summary['quarantine']} quarantine, "
        f"{summary['seconds']:.0f} s; slowest {summary['slowest']}; "
        f"draw_gaps {final['gaps']['rows']} rows"
    )
    return summary


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m sorteos.uy.silver_backfill",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--function", required=True, help="the silver Lambda")
    p.add_argument("--table", required=True, help="the DynamoDB manifest (for the years)")
    p.add_argument("--years", type=build_silver.parse_years, default=None)
    p.add_argument("--out", type=Path, default=Path("dist/uy/backfill"))
    return p


def main(argv: list[str] | None = None, lambda_client=None, dynamodb=None) -> int:
    args = build_parser().parse_args(argv)
    if lambda_client is None:  # pragma: no cover - the tests pass a fake
        import boto3
        from botocore.config import Config

        # A year takes ~1 minute; the function's limit is 15. No retries: a retried invoke
        # would run the year twice, and the first error should stop the run anyway.
        lambda_client = boto3.client(
            "lambda",
            config=Config(read_timeout=960, connect_timeout=10, retries={"total_max_attempts": 1}),
        )
    years = args.years
    if years is None:
        manifest = DynamoManifest(args.table, backfill.load_overrides(), dynamodb)
        years = build_silver.all_years(manifest.snapshot())
    try:
        summary = run(lambda_client, args.function, years, args.out)
    except CloudSilverError as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 2
    return 0 if summary["ok"] else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
