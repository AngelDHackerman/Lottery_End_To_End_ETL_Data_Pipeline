"""Start the UY nightly state machine by hand and wait for it (UY-043.3.1).

    python scripts/uy_sfn_run.py --dry-run    # or: UY_DRY_RUN=1 make uy-sfn-run
    python scripts/uy_sfn_run.py --real       # or: make uy-sfn-run (bronze, manifest, silver)

Starts one execution of ``lottery-uy-pipeline-<env>`` with ``{"dry_run": ...}``, polls it every
10 seconds and prints its output: the fetch report and the silver report, the same ones
``make uy-fetch-incremental`` and ``make uy-silver-pending`` print. Exit 0 when the execution
SUCCEEDED, 1 otherwise, with the error and cause Step Functions gives.

The execution name says who started it (``manual-dry-…`` / ``manual-real-…``), so the console
tells a hand-started run from a scheduled one (the Scheduler's get a generated id, UY-043.3.2).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from typing import Any

POLL_SECONDS = 10


def execution_input(dry_run: bool) -> str:
    return json.dumps({"dry_run": dry_run})


def execution_name(dry_run: bool, now: datetime) -> str:
    return f"manual-{'dry' if dry_run else 'real'}-{now.strftime('%Y%m%dT%H%M%SZ')}"


def report(description: dict[str, Any]) -> str:
    """What to print for a finished execution: its output, or its error and cause."""
    if description["status"] == "SUCCEEDED":
        return json.dumps(json.loads(description["output"]), indent=2, ensure_ascii=False)
    return (
        f"{description['status']}: {description.get('error', '?')}\n"
        f"{description.get('cause', '(no cause given)')}"
    )


def main(argv: list[str] | None = None) -> int:
    import boto3

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="ask the site, write nothing")
    mode.add_argument("--real", action="store_true", help="the real nightly run")
    parser.add_argument("--environment", default="prod")
    args = parser.parse_args(argv)

    session = boto3.session.Session()
    account = session.client("sts").get_caller_identity()["Account"]
    arn = (
        f"arn:aws:states:{session.region_name}:{account}:stateMachine:"
        f"lottery-uy-pipeline-{args.environment}"
    )
    sfn = session.client("stepfunctions")
    started = sfn.start_execution(
        stateMachineArn=arn,
        name=execution_name(args.dry_run, datetime.now(UTC)),
        input=execution_input(args.dry_run),
    )
    execution = started["executionArn"]
    print(f"Started {execution}", flush=True)

    while True:
        description = sfn.describe_execution(executionArn=execution)
        if description["status"] != "RUNNING":
            break
        time.sleep(POLL_SECONDS)

    print(report(description))
    return 0 if description["status"] == "SUCCEEDED" else 1


if __name__ == "__main__":
    sys.exit(main())
