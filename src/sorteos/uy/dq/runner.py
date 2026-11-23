"""Load Uruguay's silver, build the frames and run every suite on them.

    PYTHONPATH=src python -m sorteos.uy.dq.runner --silver data/uy/silver
    PYTHONPATH=src python -m sorteos.uy.dq.runner --silver ... --json-report dq.json
    PYTHONPATH=src python -m sorteos.uy.dq.runner --sync-suites

The exit code is the gate: 0 green, 1 a suite failed, 2 a table has no files. It only reads
silver; ``--sync-suites`` writes the suites' JSON into the repo and nothing else.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from sorteos.core import dq as core
from sorteos.core import silver
from sorteos.uy.dq import frames, suites

SUITES_DIR = Path("qa/uy/expectations")

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_NO_DATA = 2


def run(root: Path) -> core.Report:
    """Validate the silver under ``root``. Every suite runs, even after one fails.

    Raises :class:`sorteos.core.dq.TableEmpty` if a table has no files at all.
    """
    return check(
        core.load(root, silver.DRAWS),
        core.load(root, silver.DRAW_NUMBERS),
        core.load(root, silver.PRIZES),
        core.load(root, silver.DRAW_GAPS),
    )


def check(
    draws: pd.DataFrame, numbers: pd.DataFrame, prizes: pd.DataFrame, draw_gaps: pd.DataFrame
) -> core.Report:
    """Validate four silver tables, as :func:`sorteos.core.dq.load` returns them."""
    draws = frames.draws(draws)
    numbers = frames.draw_numbers(numbers)
    prizes = frames.prizes(prizes)
    data = {
        suites.DRAWS: draws,
        suites.DRAW_NUMBERS: numbers,
        suites.DRAW_SHAPES: frames.shapes(draws, numbers),
        suites.PRIZES: prizes,
        suites.DQ_FLAGS: frames.flags(draws, prizes),
        suites.DRAW_GAPS: frames.draw_gaps(draw_gaps),
    }
    extra = suites.run_time(frames.draw_key(draws))
    return core.Report(
        [
            core.validate(build(), data[name], extra.get(name, ()))
            for name, build in suites.BUILDERS.items()
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m sorteos.uy.dq.runner")
    parser.add_argument("--silver", type=Path, default=Path("data/uy/silver"))
    parser.add_argument("--json-report", type=Path)
    parser.add_argument("--sync-suites", action="store_true")
    args = parser.parse_args(argv)

    if args.sync_suites:
        for path in core.sync(suites.BUILDERS, SUITES_DIR):
            print(path)
        return EXIT_OK
    try:
        report = run(args.silver)
    except core.TableEmpty as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_NO_DATA
    print(report.text())
    if args.json_report:
        args.json_report.write_text(json.dumps(report.to_dict(), indent=2) + "\n")
    return EXIT_OK if report.success else EXIT_FAILED


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
