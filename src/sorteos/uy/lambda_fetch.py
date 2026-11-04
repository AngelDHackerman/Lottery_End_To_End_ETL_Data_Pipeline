"""The fetch Lambda (UY-042.3; DESIGN.md D26, D29). In this PR it only probes.

    {"mode": "probe"}                               # the newest draw of every source
    {"mode": "probe", "sources": ["resultados"]}    # only these sources

**Why a probe first (D26).** UY-005 reached the site without a proxy from CloudShell, which
leaves from other IPs than a Lambda does. The probe asks the site again for the newest key with
a draw of each source, keys whose bytes the manifest already holds, and says per key whether
the site answered and whether it served the same bytes (SHA-256 against ``content_sha256``).
It writes nothing: no bronze, no manifest row. Fetching for real starts with UY-043, the day
the local incremental is switched off (G4), so until then the table stays equal to SQLite.

A different SHA is reported, not failed: it would mean the site changed a page it had already
published, which is worth knowing but is not the question D26 asks. ``ok`` is whether every
key answered 200.

The client is ``privacy.polite_client`` (P5): 1 request per second, the DET_INVALIDAS guard and
the research User-Agent. Fewer retries than the backfill, so a blocked site ends the probe
within the function's timeout instead of backing off for minutes.
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
from sorteos.core.http_client import FetchError
from sorteos.core.manifest_dynamodb import DynamoManifest
from sorteos.uy import backfill, privacy
from sorteos.uy.sources import ALL_SOURCES

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

PROBE_RETRIES = 2
PROBE_BACKOFF_CAP = 10.0


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


def handler(event: dict | None, context: Any = None) -> dict[str, Any]:
    event = event or {}
    mode = event.get("mode", "probe")
    if mode != "probe":
        raise ValueError(f"mode {mode!r}: only 'probe' until UY-043 (G4)")
    sources = event.get("sources") or list(ALL_SOURCES)
    unknown = sorted(set(sources) - set(ALL_SOURCES))
    if unknown:
        raise ValueError(f"unknown sources: {unknown}")
    manifest = DynamoManifest(os.environ["MANIFEST_TABLE"], backfill.load_overrides())
    client = privacy.polite_client(max_retries=PROBE_RETRIES, backoff_cap=PROBE_BACKOFF_CAP)
    report = probe(manifest, client, sources)
    log.info(json.dumps(report))
    return report
