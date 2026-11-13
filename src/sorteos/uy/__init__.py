"""Loterías de Uruguay (DNLQ, www.loteria.gub.uy) — the first country under ``sorteos``.

Modules:
- sources:  the URLs per source (consolidated page, per-game extracts) for a date.
- classify: decide draw / no_draw from a raw page, so the manifest knows what it holds.
- backfill: CLI that walks a date range and lands raw pages in bronze.

The HTTP client and the bronze store live in ``sorteos.core``; this package is what is
specific to Uruguay (docs/uruguay/DESIGN.md, D1).
"""
