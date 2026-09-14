#!/usr/bin/env python3
"""Run the Silver data-quality suites and exit non-zero on failure (PR-032).

    python scripts/run_dq.py --bucket lottery-partitioned-storage-prod
    python scripts/run_dq.py --bucket ... --dataset premios --json-report dq.json
    python scripts/run_dq.py --sync-suites          # regenerate the committed suite JSON

The non-zero exit is the whole point: PR-033 wires this into the Step Function between the
Silver crawlers and the Gold CTAS map state, so a failure here is what stops a bad Silver
layer from being aggregated into Gold.

Reads only. It never writes to the data buckets — the one path that writes anything is
``--sync-suites``, which touches the repo, not S3.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Support being run as a plain script (`python scripts/run_dq.py`) from a checkout, where
# `src/` is not on sys.path. In the PR-033 job the package is unzipped at the root and this
# is a no-op. Done before the loteria imports on purpose.
REPO_ROOT = Path(__file__).resolve().parent.parent
if (REPO_ROOT / "src").is_dir():
    sys.path.insert(0, str(REPO_ROOT / "src"))

from loteria.common.logging_setup import configure_logging  # noqa: E402
from loteria.dq.runner import (  # noqa: E402
    DATASET_SUITES,
    SILVER_PREFIX_DEFAULT,
    SilverDatasetEmpty,
    format_report,
    quiet_gx,
    run_dq,
)
from loteria.dq.suites import SUITE_BUILDERS  # noqa: E402

#: Where the roadmap asks for the GX project to live. Holds the generated suite JSON that
#: `tests/unit/test_dq_suites.py` compares the Python builders against.
GX_CONTEXT_DIR = REPO_ROOT / "qa" / "great_expectations"

EXIT_OK = 0
EXIT_DQ_FAILED = 1
EXIT_NO_DATA = 2
EXIT_USAGE = 3


# --------------------------------------------------------------------------------------
# Suite sync
# --------------------------------------------------------------------------------------
def normalize_suite_json(path: Path) -> None:
    """Strip GX's volatile fields from a written suite file and sort it.

    GX mints a fresh random UUID for the suite **and for every expectation in it** on each
    write. Left alone, re-running ``--sync-suites`` after changing one expectation produces
    a diff touching every line of the file, which destroys the only reason to commit it: so
    a reviewer can see what the data contract is and what a change to it actually changed.

    Dropping the ids is safe — GX reads these files back and re-mints ids in memory (there
    is no cross-file reference to them), and it does not rewrite the file on load.
    ``great_expectations_version`` is kept: it churns only on a real GX upgrade, which is a
    change worth seeing in the diff.
    """
    suite = json.loads(path.read_text(encoding="utf-8"))
    suite.pop("id", None)
    for expectation in suite.get("expectations", []):
        expectation.pop("id", None)

    path.write_text(
        json.dumps(suite, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def sync_suites(context_dir: Path = GX_CONTEXT_DIR) -> list[str]:
    """Materialize the Python-defined suites into the committed GX project.

    ``loteria.dq.suites`` is the source of truth; this only renders it. Run it after
    changing an expectation, then commit the diff — the JSON is what makes the data
    contract reviewable without executing anything.
    """
    import great_expectations as gx

    quiet_gx()

    context_dir.mkdir(parents=True, exist_ok=True)
    context = gx.get_context(mode="file", context_root_dir=str(context_dir))

    written = []
    for name, build in SUITE_BUILDERS.items():
        # add_or_update, not add: this has to be re-runnable against an existing project.
        context.suites.add_or_update(build())
        normalize_suite_json(context_dir / "expectations" / f"{name}.json")
        written.append(name)

    return written


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_dq.py",
        description="Validate the Silver layer against its Great Expectations suites.",
    )
    parser.add_argument(
        "--bucket",
        default=os.environ.get("PARTITIONED_BUCKET"),
        help="Partitioned bucket holding silver/. Defaults to $PARTITIONED_BUCKET.",
    )
    parser.add_argument(
        "--silver-prefix",
        default=SILVER_PREFIX_DEFAULT,
        help=f"Prefix the Silver datasets live under (default: {SILVER_PREFIX_DEFAULT!r}).",
    )
    parser.add_argument(
        "--dataset",
        action="append",
        dest="datasets",
        choices=sorted(DATASET_SUITES),
        help="Validate only this dataset. Repeatable. Default: all of them.",
    )
    parser.add_argument(
        "--json-report",
        type=Path,
        help="Also write the full result as JSON to this path.",
    )
    parser.add_argument(
        "--sync-suites",
        action="store_true",
        help="Regenerate qa/great_expectations/ from the Python suites and exit.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging("dq")

    if args.sync_suites:
        written = sync_suites()
        print(f"Synced {len(written)} suite(s) to {GX_CONTEXT_DIR}: {', '.join(written)}")
        return EXIT_OK

    if not args.bucket:
        # argparse `required=True` would refuse `--sync-suites` too, which needs no bucket.
        print(
            "error: --bucket is required (or set PARTITIONED_BUCKET)",
            file=sys.stderr,
        )
        return EXIT_USAGE

    try:
        report = run_dq(
            bucket=args.bucket,
            datasets=args.datasets,
            silver_prefix=args.silver_prefix,
        )
    except SilverDatasetEmpty as exc:
        # Deliberately its own exit code. "There is no Silver data" is an operational
        # problem (wrong bucket, transformer never ran); "the Silver data is wrong" is a
        # quality problem. PR-033 should be able to tell the two apart in an alert.
        print(f"NO DATA: {exc}", file=sys.stderr)
        return EXIT_NO_DATA

    print(format_report(report))

    if args.json_report:
        args.json_report.parent.mkdir(parents=True, exist_ok=True)
        args.json_report.write_text(
            json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        print(f"\nJSON report written to {args.json_report}")

    return EXIT_OK if report.success else EXIT_DQ_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
