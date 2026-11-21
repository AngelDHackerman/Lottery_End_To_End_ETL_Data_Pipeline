"""The UY silver gate as a Glue 5.0 job (UY-043.4). DESIGN.md D20, D30.

Glue runs ``scripts/uy_dq_glue_main.py``, which calls :func:`main`. It copies ``uy/silver/``
to disk and runs the same :func:`sorteos.uy.dq.runner.run` as ``make uy-dq`` (owner, UY-043.4
2a): the cloud and the laptop execute one code path, and silver is ~4 MB, so the copy is
seconds.

**A failure is an exception** (owner, UY-043.4 3a). The Glue run fails, ``ValidateSilver``
fails with it (``glue:startJobRun.sync`` waits for the job), the execution ends FAILED and the
pipeline's alarm sends the e-mail. The exception's message is what Step Functions shows as the
cause, so it names the suite, the expectation and the column.

**Where the output goes.** This job never creates a SparkContext: Glue 5.0 is only the way to
get Python 3.11 for GX. Continuous logging ships Spark's log4j, so a per-job log group would
stay empty (master's PR-033.1). Everything printed here lands in the account-wide
``/aws-glue/jobs/output``, in the stream named after the job run id; ``make uy-dq-run`` reads
it back.

**The start-up is measured from here** (D30). :data:`START_MARK` carries the time of this
job's first line; the run's ``StartedOn`` minus that is what Glue spent provisioning and
installing the zip of wheels before the script ran.

Arguments arrive as ``--NAME value`` in ``sys.argv``, among others Glue adds on its own, so
they are scanned for by name (``awsglue`` exists only inside Glue, and a test must import this).
"""

from __future__ import annotations

import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REQUIRED_ARGS = ("SILVER_BUCKET", "SILVER_PREFIX")
#: ``RUN_ID`` is the Step Functions execution name; by hand it is absent.
OPTIONAL_ARGS = ("RUN_ID",)

START_MARK = "UY DQ START"
RESULT_MARK = "UY DQ RESULT"
WORKERS = 16


class SilverDataQualityFailed(Exception):
    """An expectation failed: the job did its work and silver is wrong."""


class SilverNotFound(Exception):
    """Nothing to validate: a wiring problem (bucket, prefix, role), not a data one."""


def parse_args(argv: list[str]) -> dict[str, str]:
    """The ``--NAME value`` / ``--NAME=value`` arguments this job knows; the rest is ignored."""
    found: dict[str, str] = {}
    for name in (*REQUIRED_ARGS, *OPTIONAL_ARGS):
        flag = f"--{name}"
        for index, token in enumerate(argv):
            if token == flag and index + 1 < len(argv):
                found[name] = argv[index + 1]
                break
            if token.startswith(f"{flag}="):
                found[name] = token.split("=", 1)[1]
                break
    missing = [name for name in REQUIRED_ARGS if not found.get(name)]
    if missing:
        raise SystemExit(f"Missing required job argument(s): {', '.join(missing)}")
    if not found["SILVER_PREFIX"].endswith("/"):
        # "uy/silver" would also list "uy/silver_old/…" and cut the keys one character off.
        raise SystemExit("--SILVER_PREFIX must end with '/'")
    return found


def download(client, bucket: str, prefix: str, root: Path) -> tuple[int, int]:
    """Copy every object under ``prefix`` to ``root``; return (files, bytes).

    Zero-byte objects are copied too: a partition that disappeared is an empty Parquet in S3
    (UY-042.4.1), and the local gate reads those files as well.
    """
    keys = [
        obj["Key"]
        for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix)
        for obj in page.get("Contents", [])
        if not obj["Key"].endswith("/")
    ]

    def one(key: str) -> int:
        content = client.get_object(Bucket=bucket, Key=key)["Body"].read()
        path = root / key[len(prefix) :]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return len(content)

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        return len(keys), sum(pool.map(one, keys))


def failure_summary(report) -> str:
    """One line per failed expectation: what Step Functions shows as the cause."""
    lines = []
    for result in report.results:
        for o in result.failures:
            detail = o.error or f"{o.unexpected_count} unexpected, e.g. {o.sample}"
            lines.append(f"{result.suite}: {o.expectation} on {o.column}: {detail}")
    return "; ".join(lines) or "no suite ran"


def main(argv: list[str] | None = None, s3=None) -> dict[str, Any]:
    began = time.monotonic()
    args = parse_args(sys.argv if argv is None else argv)
    bucket, prefix = args["SILVER_BUCKET"], args["SILVER_PREFIX"]
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"{START_MARK} {now} run_id={args.get('RUN_ID') or '-'}", flush=True)

    # After the first line, so the mark is not delayed by imports: pandas and GX take seconds.
    from sorteos.core import dq as core
    from sorteos.uy.dq import runner

    if s3 is None:  # pragma: no cover - the real client, only inside Glue
        import boto3
        from botocore.config import Config

        s3 = boto3.client("s3", config=Config(max_pool_connections=WORKERS))
    imported = time.monotonic()

    with tempfile.TemporaryDirectory(prefix="uy-silver-") as tmp:
        root = Path(tmp)
        files, size = download(s3, bucket, prefix, root)
        downloaded = time.monotonic()
        print(f"downloaded s3://{bucket}/{prefix}: {files} files, {size / 1e6:.1f} MB", flush=True)
        if not files:
            raise SilverNotFound(f"nothing under s3://{bucket}/{prefix}: check the wiring")
        try:
            report = runner.run(root)
        except core.TableEmpty as exc:
            raise SilverNotFound(f"s3://{bucket}/{prefix}: {exc}") from exc
    done = time.monotonic()

    print(report.text(), flush=True)
    timings = {
        "imports": round(imported - began, 1),
        "download": round(downloaded - imported, 1),
        "validate": round(done - downloaded, 1),
        "total": round(done - began, 1),
    }
    verdict = "PASS" if report.success else "FAIL"
    print(f"{RESULT_MARK}: {verdict} seconds={timings}", flush=True)
    if not report.success:
        raise SilverDataQualityFailed(f"UY silver failed its gate. {failure_summary(report)}")
    return {
        "success": True,
        "files": files,
        "suites": {
            r.suite: {"expectations": len(r.outcomes), "rows": r.rows} for r in report.results
        },
        "seconds": timings,
    }


if __name__ == "__main__":  # pragma: no cover
    main()
