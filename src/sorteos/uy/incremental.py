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
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
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
        start = window_start(manifest, today)
        older = [(source, day) for source, day in manifest.open_keys() if day < start]
        job = backfill.Backfill(
            client or privacy.polite_client(),
            store,
            manifest,
            sources=backfill.resolve_sources(SOURCES),
            today=today,
            max_requests=args.max_requests,
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

        pending_path = args.root / PENDING
        years = read_pending(pending_path) | {day.year for _, day in stats.changed}
        lines = [
            f"window {start} .. {today}, open keys before it: {len(older)}",
            f"requests {stats.requests}, skipped {stats.skipped}, changed {len(stats.changed)}",
            *(f"changed {source} {day}" for source, day in sorted(stats.changed)),
        ]
        run = build_silver.new_run("incremental")
        if years:
            write_pending(pending_path, years)
            counts = build_silver.rebuild(manifest, store, args.silver, sorted(years), run)
            pending_path.unlink()
            lines.append(build_silver.format_counts(counts))
        else:
            lines.append("silver: nothing changed")
        report = build_silver.detect_gaps(args.silver, run, today)
        lines.append(build_silver.format_gaps(report))
        print("\n".join(lines), file=sys.stderr)
    finally:
        manifest.close()
    return 0 if report.rows is not None else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
