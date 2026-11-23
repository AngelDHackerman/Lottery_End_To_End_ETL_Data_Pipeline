"""UY-020: every URL the manifest recorded must come out of the YAML again, byte for byte.

The manifest stores, per (source, draw_date), the URL that was actually requested — by the
code that had the paths written by hand. Rebuilding all of them from site.yaml and
games/*.yaml proves the move to configuration changed nothing the site sees.

    PYTHONPATH=src python scripts/uy_golden_urls.py data/uy/manifest.sqlite
    PYTHONPATH=src python scripts/uy_golden_urls.py data/uy/manifest.sqlite \\
        --write-sample tests/fixtures/uy/golden_urls.json

The pozos PDF is skipped: its URL is the results page's own link, not something a date
rebuilds (classify.pozos_href). The manifest is opened read-only.

``--write-sample`` keeps a fixed, hand-shaped sample for CI, which has no manifest: per
source the first and last rows, the last before and first after 2018-11-30 (the day the
site moved to PDF extracts), and the first row of each one-/two-digit day and month mix.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

from sorteos.uy.sources import ALL_SOURCES

PDF_SWITCH = date(2018, 11, 30)


def read_rows(manifest: Path) -> list[tuple[str, str, str]]:
    db = sqlite3.connect(f"file:{manifest}?mode=ro", uri=True)
    try:
        return db.execute("SELECT source, draw_date, url FROM manifest ORDER BY 1, 2").fetchall()
    finally:
        db.close()


def compare(rows) -> tuple[int, int, list[str]]:
    """Return (checked, skipped, mismatches) for ``(source, draw_date, url)`` rows."""
    checked, skipped, mismatches = 0, 0, []
    for name, day_text, url in rows:
        source = ALL_SOURCES.get(name)
        if source is None:
            mismatches.append(f"{name} {day_text}: no such source in the YAML")
            continue
        if source.path is None:
            skipped += 1
            continue
        day = date.fromisoformat(day_text)
        checked += 1
        if not source.applies_to(day):
            mismatches.append(f"{name} {day_text}: before the source's valid_from")
        elif (rebuilt := source.url(day)) != url:
            mismatches.append(f"{name} {day_text}: manifest {url} != yaml {rebuilt}")
    return checked, skipped, mismatches


def sample(rows) -> list[dict]:
    by_source: dict[str, list[tuple[str, str, str]]] = {}
    for row in rows:
        if ALL_SOURCES.get(row[0]) is not None and ALL_SOURCES[row[0]].path is not None:
            by_source.setdefault(row[0], []).append(row)
    picked: list[tuple[str, str, str]] = []
    for name in sorted(by_source):
        source_rows = sorted(by_source[name], key=lambda r: r[1])
        days = [date.fromisoformat(r[1]) for r in source_rows]
        chosen = {0, len(source_rows) - 1}
        before = [i for i, d in enumerate(days) if d < PDF_SWITCH]
        after = [i for i, d in enumerate(days) if d >= PDF_SWITCH]
        chosen |= {before[-1]} if before else set()
        chosen |= {after[0]} if after else set()
        for short_day in (True, False):
            for short_month in (True, False):
                match = [
                    i
                    for i, d in enumerate(days)
                    if (d.day < 10) == short_day and (d.month < 10) == short_month
                ]
                chosen |= {match[0]} if match else set()
        picked.extend(source_rows[i] for i in sorted(chosen))
    return [{"source": s, "draw_date": d, "url": u} for s, d, u in picked]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("manifest", type=Path)
    p.add_argument("--write-sample", type=Path, help="also write the CI sample to this file")
    args = p.parse_args(argv)

    rows = read_rows(args.manifest)
    checked, skipped, mismatches = compare(rows)
    for line in mismatches[:20]:
        print(line, file=sys.stderr)
    print(
        f"{checked} URLs rebuilt from the YAML, {len(mismatches)} differ, {skipped} skipped (pozos)"
    )
    if args.write_sample:
        chosen = sample(rows)
        args.write_sample.write_text(json.dumps(chosen, indent=2) + "\n", encoding="utf-8")
        print(f"{len(chosen)} rows written to {args.write_sample}")
    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main())
