"""Run the UY silver gate's Glue job by hand, wait, and measure its start-up (UY-043.4, D30).

    python scripts/uy_dq_run.py            # or: make uy-dq-run
    python scripts/uy_dq_run.py --timeout 30

Starts one run of ``lottery-uy-silver-dq-<env>``, polls it every 10 seconds, then prints what
the job printed (from /aws-glue/jobs/output, the stream named after the run id) and the
timings. The job only reads uy/silver/. Exit 0 when the run SUCCEEDED, 1 otherwise.

**Start-up** is the job's first line (its ``UY DQ START`` mark) minus the run's ``StartedOn``:
what Glue spent provisioning and installing the zip of wheels before the script ran. Master's
job spent ~21 minutes there installing GX from PyPI; D30 is the hypothesis that the zip brings
it down. ``ExecutionTime`` is what Glue bills.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import UTC, datetime
from typing import Any

POLL_SECONDS = 10
LOG_GROUP = "/aws-glue/jobs/output"
START_MARK = "UY DQ START"  # sorteos.uy.dq.glue_job.START_MARK
FINAL = {"SUCCEEDED", "FAILED", "TIMEOUT", "STOPPED", "ERROR", "EXPIRED"}
#: CloudWatch receives the last lines a little after the run ends.
LOG_TRIES = 6


def first_line_at(lines: list[str]) -> datetime | None:
    """When the script started, from its ``UY DQ START <iso>`` line."""
    for line in lines:
        if line.startswith(START_MARK):
            stamp = line[len(START_MARK) :].split()[0]
            return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    return None


def timings(run: dict[str, Any], lines: list[str]) -> dict[str, Any]:
    """Wall clock, start-up and billed seconds of a finished run."""
    started, completed = run["StartedOn"], run.get("CompletedOn")
    first = first_line_at(lines)
    return {
        "wall_seconds": round((completed - started).total_seconds()) if completed else None,
        "startup_seconds": round((first - started).total_seconds()) if first else None,
        "billed_seconds": run.get("ExecutionTime"),
    }


def log_lines(logs, run_id: str) -> list[str]:
    pages = logs.get_paginator("filter_log_events").paginate(
        logGroupName=LOG_GROUP, logStreamNamePrefix=run_id
    )
    events = [event for page in pages for event in page["events"]]
    return [e["message"].rstrip("\n") for e in sorted(events, key=lambda e: e["timestamp"])]


def main(argv: list[str] | None = None) -> int:
    import boto3

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--environment", default="prod")
    parser.add_argument("--timeout", type=int, help="minutes, for this run only")
    args = parser.parse_args(argv)

    glue = boto3.client("glue")
    job = f"lottery-uy-silver-dq-{args.environment}"
    extra = {"Timeout": args.timeout} if args.timeout else {}
    run_id = glue.start_job_run(JobName=job, **extra)["JobRunId"]
    print(f"Started {job} {run_id}", flush=True)

    while True:
        run = glue.get_job_run(JobName=job, RunId=run_id)["JobRun"]
        if run["JobRunState"] in FINAL:
            break
        time.sleep(POLL_SECONDS)

    logs = boto3.client("logs")
    lines: list[str] = []
    for _ in range(LOG_TRIES):
        lines = log_lines(logs, run_id)
        if any("UY DQ RESULT" in line for line in lines) or run["JobRunState"] != "SUCCEEDED":
            break
        time.sleep(POLL_SECONDS)

    print("\n".join(lines) or f"(no lines in {LOG_GROUP} for {run_id})")
    print(f"{run['JobRunState']}: {timings(run, lines)}")
    if run.get("ErrorMessage"):
        print(run["ErrorMessage"])
    return 0 if run["JobRunState"] == "SUCCEEDED" else 1


if __name__ == "__main__":
    sys.exit(main())
