"""The fetch Lambda (UY-042.3, UY-043.2; DESIGN.md D26, D29).

    {"mode": "probe"}                               # the newest draw of every source
    {"mode": "probe", "sources": ["resultados"]}    # only these sources
    {"mode": "incremental"}                         # the nightly fetch
    {"mode": "incremental", "dry_run": true}        # ask the site, write nothing
    {"mode": "incremental", "max_requests": 50}     # stop after 50 (default 400)

**The incremental (UY-043.2)** is ``incremental.fetch_step``, the code the local run uses,
against the DynamoDB manifest and bronze in S3. Each key that changes marks its year in
``PENDING#silver`` the moment its manifest row is written (``PendingYears.add``), so a run
cut short by the timeout still hands silver every year it touched. The silver Lambda reads
that item (``{"pending": true}``).

**Its dry run** (owner, UY-043.2 a) asks the site for real and decides every key exactly as a
real run would, with the manifest's own code (``DryRunManifest``), but keeps the writes in
memory: no bronze, no manifest row, no pending year. The report says what would have changed.

**Why a probe first (D26).** UY-005 reached the site without a proxy from CloudShell, which
leaves from other IPs than a Lambda does. The probe asks the site again for the newest key with
a draw of each source, keys whose bytes the manifest already holds, and says per key whether
the site answered and whether it served the same bytes (SHA-256 against ``content_sha256``).
It writes nothing: no bronze, no manifest row. Fetching for real starts with UY-043, the day
the local incremental is switched off (G4), so until then the table stays equal to SQLite.

A different SHA is reported, not failed: it would mean the site changed a page it had already
published, which is worth knowing but is not the question D26 asks. ``ok`` is whether every
key answered 200.

For both modes the client is ``privacy.polite_client`` (P5): 1 request per second, the
DET_INVALIDAS guard and the research User-Agent. The probe uses fewer retries than the
backfill, so a blocked site ends it within the function's timeout instead of backing off for
minutes.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from datetime import date
from typing import Any

from sorteos.core import manifest as mf
from sorteos.core.bronze import DryRunStore, S3BronzeStore
from sorteos.core.http_client import FetchError
from sorteos.core.manifest_dynamodb import DryRunManifest, DynamoManifest, PendingYears
from sorteos.uy import backfill, incremental, privacy
from sorteos.uy.sources import ALL_SOURCES, COUNTRY

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

PROBE_RETRIES = 2
PROBE_BACKOFF_CAP = 10.0
# The incremental's default budget (owner, UY-043.2 a): a normal night is ~40-60 requests;
# 400 at 1 per second fit the 900 s timeout with room for retries. Whatever is not asked
# tonight is asked tomorrow: the window starts after the last draw the manifest holds.
DEFAULT_MAX_REQUESTS = 400


def probe(manifest: mf.Manifest, client, sources: list[str]) -> dict[str, Any]:
    results = []
    for source in sources:
        span = manifest.date_range(source)
        if span is None:
            results.append({"source": source, "error": "no draw in the manifest"})
            continue
        day = span[1]
        row = manifest.get(source, date.fromisoformat(day))
        entry: dict[str, Any] = {"source": source, "draw_date": day, "url": row["url"]}
        started = time.monotonic()
        try:
            result = client.get(row["url"])
        except FetchError as exc:
            entry["error"] = str(exc)
        else:
            sha = hashlib.sha256(result.content).hexdigest()
            entry |= {
                "status": result.status,
                "bytes": len(result.content),
                "same_bytes": sha == row["content_sha256"],
            }
        entry["seconds"] = round(time.monotonic() - started, 2)
        results.append(entry)
    return {
        "mode": "probe",
        "ok": all(r.get("status") == 200 for r in results),
        "same_bytes": sum(1 for r in results if r.get("same_bytes")),
        "keys": len(results),
        "results": results,
    }


def run_incremental(
    manifest: mf.Manifest,
    store,
    client,
    today: date,
    *,
    pending: PendingYears | None,
    max_requests: int | None = None,
) -> dict[str, Any]:
    """``fetch_step``, with each changed key's year marked in ``pending`` as it changes (no
    ``pending``: the dry run). Returns the report."""
    on_change = None if pending is None else (lambda _source, day: pending.add({day.year}))
    fetched = incremental.fetch_step(client, store, manifest, today, max_requests, on_change)
    stats = fetched.stats
    return {
        "mode": "incremental",
        "dry_run": pending is None,
        "window": [fetched.start.isoformat(), today.isoformat()],
        "open_keys_before_window": fetched.older,
        "requests": stats.requests,
        "skipped": stats.skipped,
        "by_state": dict(sorted(stats.by_state.items())),
        "changed": [[source, day.isoformat()] for source, day in sorted(stats.changed)],
        "years": sorted(fetched.years),
    }


def _max_requests(event: dict) -> int:
    value = event.get("max_requests", DEFAULT_MAX_REQUESTS)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"max_requests must be a positive integer: {value!r}")
    return value


def handler(
    event: dict | None, context: Any = None, s3=None, dynamodb=None, client=None
) -> dict[str, Any]:
    event = event or {}
    mode = event.get("mode", "probe")
    if mode == "incremental":
        return _incremental(event, s3, dynamodb, client)
    if mode != "probe":
        raise ValueError(f"mode {mode!r}: 'probe' or 'incremental'")
    sources = event.get("sources") or list(ALL_SOURCES)
    unknown = sorted(set(sources) - set(ALL_SOURCES))
    if unknown:
        raise ValueError(f"unknown sources: {unknown}")
    manifest = DynamoManifest(os.environ["MANIFEST_TABLE"], backfill.load_overrides())
    client = privacy.polite_client(max_retries=PROBE_RETRIES, backoff_cap=PROBE_BACKOFF_CAP)
    report = probe(manifest, client, sources)
    log.info(json.dumps(report))
    return report


def _incremental(event: dict, s3, dynamodb, client) -> dict[str, Any]:
    dry_run = bool(event.get("dry_run"))
    max_requests = _max_requests(event)
    table = os.environ["MANIFEST_TABLE"]
    overrides = backfill.load_overrides()
    s3_store = S3BronzeStore(os.environ["BRONZE_BUCKET"], os.environ["BRONZE_PREFIX"], COUNTRY, s3)
    store = DryRunStore(s3_store) if dry_run else s3_store
    manifest = (DryRunManifest if dry_run else DynamoManifest)(table, overrides, dynamodb)
    report = run_incremental(
        manifest,
        store,
        client or privacy.polite_client(),
        backfill.today_in_uruguay(),
        pending=None if dry_run else PendingYears(table, dynamodb),
        max_requests=max_requests,
    )
    if isinstance(store, DryRunStore):
        report["bronze_not_written"] = sorted(store.written)
    log.info(json.dumps(report))
    return report
