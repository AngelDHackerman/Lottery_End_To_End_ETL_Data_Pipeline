"""Loterías de Uruguay (DNLQ, www.loteria.gub.uy) — beta extension of the pipeline.

Lives beside ``loteria`` on purpose, not inside it: the Lambda, Glue and DQ build scripts
copy ``src/loteria`` and nothing else, so nothing here can ride into a Santa Lucía artifact
or trigger a redeploy of one. See ``roadmap-uruguay.md`` (rule 6) — the package name is
provisional until UY-010.

Subpackages / modules:
- http_client: the only way this package talks to the network — rate limit, retries and
               the ``DET_INVALIDAS`` privacy blocklist live here and nowhere else.
- sources:     the URLs per source (consolidated page, per-game extracts) for a date.
- classify:    decide draw / no_draw from a raw page, so the manifest knows what it holds.
- bronze:      local raw store + manifest (the manifest is the cache, not bronze).
- backfill:    CLI that walks a date range and lands raw pages in bronze.
"""
