"""The daily run (UY-027.1): fetch what may have changed, then rewrite silver for it.

    python -m sorteos.uy.incremental
    python -m sorteos.uy.incremental --max-requests 50

What it asks for (docs/uruguay/DESIGN.md, D16, P11, P12):

- the last 7 days: the 3-day settle, the gap detector's 3-day window, plus one. When the
  manifest's last results page with a draw is older than that, it starts the day after it
  instead, so a run that did not happen for a while leaves no hole;
- every key the manifest still has open, whatever its date, and only that key: the pozos PDF
  in ``error`` close themselves after at most three identical failures (D11);
- the four kinds of source: results, PHP extracts, extract PDFs (a backup, not parsed; D19
  starts it here) and pozos PDFs.

Then every year with a key that changed is rewritten in silver (D17). Those years are written
to ``silver_pending.json`` before silver starts and removed when it ends, so a run cut in
between still rewrites them next time, when the manifest no longer changes. Build silver once
with ``make uy-silver`` first: the incremental only rewrites the years it touches.

Last, the gap detector rewrites ``draw_gaps`` (step 2 in DESIGN), on every run, even when
nothing changed: a site that stops publishing changes nothing, and that is the gap to see.
It skips when silver has quarantine and the run exits 1 (owner, UY-028 3a).

**Two steps (UY-043.1).** ``fetch_step`` asks the site and returns what changed; ``silver_step``
rewrites those years and ``draw_gaps``. Neither knows where the manifest, bronze or silver
live, so the cloud runs the same two steps in two Lambdas (UY-043.2), with the pending years
in DynamoDB instead of ``silver_pending.json``. ``main`` is the local run: both, in order.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from sorteos.core import bronze
from sorteos.core import manifest as mf
from sorteos.core.http_client import PoliteClient
from sorteos.uy import backfill, build_silver, privacy
from sorteos.uy.sources import COUNTRY, RESULTADOS

logger = logging.getLogger(__name__)

WINDOW_DAYS = 7
SOURCES = "resultados,extractos,pdf,pozos"
PENDING = "silver_pending.json"


def window_start(manifest: mf.Manifest, today: date) -> date:
    start = today - timedelta(days=WINDOW_DAYS - 1)
    span = manifest.date_range(RESULTADOS.name)
    if span:
        start = min(start, date.fromisoformat(span[1]) + timedelta(days=1))
    return start


@dataclass(frozen=True)
class Fetched:
    """What ``fetch_step`` did: the window, the old open keys it also asked for, the counts."""

    start: date
    today: date
    older: int
    stats: backfill.RunStats

    @property
    def years(self) -> set[int]:
        """The years silver has to rewrite (D17)."""
        return {day.year for _, day in self.stats.changed}

    def lines(self) -> list[str]:
        return [
            f"window {self.start} .. {self.today}, open keys before it: {self.older}",
            f"requests {self.stats.requests}, skipped {self.stats.skipped}, "
            f"changed {len(self.stats.changed)}",
            *(f"changed {source} {day}" for source, day in sorted(self.stats.changed)),
        ]


def fetch_step(
    client: PoliteClient,
    store,
    manifest: mf.Manifest,
    today: date,
    max_requests: int | None = None,
    on_change: Callable[[str, date], None] | None = None,
) -> Fetched:
    """Ask for the window and for every older open key; write bronze and the manifest.
    ``on_change(source, day)`` runs as each key changes (``backfill.Backfill``)."""
    start = window_start(manifest, today)
    older = [(source, day) for source, day in manifest.open_keys() if day < start]
    job = backfill.Backfill(
        client,
        store,
        manifest,
        sources=backfill.resolve_sources(SOURCES),
        today=today,
        max_requests=max_requests,
        on_change=on_change,
    )
    job.run(start, today)
    stats = job.run_keys(older)
    logger.info(
        "incremental fetched",
        extra={
            "start": start.isoformat(),
            "open_keys_before_start": len(older),
            "requests": stats.requests,
            "skipped": stats.skipped,
            "changed": len(stats.changed),
            **stats.by_state,
        },
    )
    return Fetched(start, today, len(older), stats)


def silver_step(
    manifest: mf.Manifest, store, out: Path, years: set[int], today: date
) -> tuple[list[str], build_silver.GapReport]:
    """Rewrite ``years`` (none: silver is left alone), then ``draw_gaps``, always."""
    run = build_silver.new_run("incremental")
    if years:
        counts = build_silver.rebuild(manifest, store, out, sorted(years), run)
        lines = [build_silver.format_counts(counts)]
    else:
        lines = ["silver: nothing changed"]
    report = build_silver.detect_gaps(out, run, today)
    return [*lines, build_silver.format_gaps(report)], report


def read_pending(path: Path) -> set[int]:
    return set(json.loads(path.read_text())) if path.exists() else set()


def write_pending(path: Path, years: set[int]) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(sorted(years)))
    tmp.replace(path)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m sorteos.uy.incremental",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--root", type=Path, default=backfill.DEFAULT_ROOT)
    p.add_argument("--silver", type=Path, default=build_silver.DEFAULT_SILVER)
    p.add_argument("--max-requests", type=int, default=None)
    return p


def main(argv: list[str] | None = None, *, client: PoliteClient | None = None) -> int:
    args = build_parser().parse_args(argv)
    from loteria.common.logging_setup import configure_logging

    configure_logging("loteria-uy-incremental")
    manifest = mf.SqliteManifest(args.root / "manifest.sqlite", backfill.load_overrides())
    store = bronze.BronzeStore(args.root, COUNTRY)
    try:
        today = backfill.today_in_uruguay()
        fetched = fetch_step(
            client or privacy.polite_client(), store, manifest, today, args.max_requests
        )
        # Written before silver starts and removed when it ends: a run cut in between still
        # rewrites these years next time, when the manifest no longer changes.
        pending_path = args.root / PENDING
        years = read_pending(pending_path) | fetched.years
        if years:
            write_pending(pending_path, years)
        lines, report = silver_step(manifest, store, args.silver, years, today)
        if years:
            pending_path.unlink()
        print("\n".join([*fetched.lines(), *lines]), file=sys.stderr)
    finally:
        manifest.close()
    return 0 if report.rows is not None else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
