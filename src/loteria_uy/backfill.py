"""Walk a date range and land raw pages in local bronze (UY backfill, local-only beta).

    python -m loteria_uy.backfill --start 2006-08-01 --end today
    python -m loteria_uy.backfill --start 2016-01-01 --end 2016-12-31 --sources resultados
    python -m loteria_uy.backfill --report

Day by day, the results page first: it is the discovery layer, and the per-game sources are
requested only for games it lists on that day. A day already in a final manifest state is
never requested again (``--refresh`` overrides), so the run can be stopped and resumed at
any point and a second pass over the same range costs only what the first one left open.

At 1 request per second the full range is a few hours: ~7,400 results pages, plus one
extract per game drawn. ``--max-requests`` caps a session.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from loteria_uy import bronze, classify
from loteria_uy.http_client import FetchError, PoliteClient
from loteria_uy.sources import ALL_SOURCES, RESULTADOS, SOURCE_GROUPS, Source

logger = logging.getLogger(__name__)

URUGUAY = ZoneInfo("America/Montevideo")
DEFAULT_ROOT = Path("data/uy")
# The earliest results page with data is 2006-08-11 (bisected 2026-10-04); start the
# default a little before it so the manifest itself records where the history begins.
DEFAULT_START = date(2006, 8, 1)
# An empty page this many days old is a day without a draw, not a draw not yet published.
DEFAULT_SETTLE_DAYS = 3


def today_in_uruguay() -> date:
    return datetime.now(URUGUAY).date()


def daterange(start: date, end: date) -> Iterator[date]:
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)


@dataclass
class RunStats:
    requests: int = 0
    skipped: int = 0
    by_state: dict = field(default_factory=dict)

    def count(self, state: str) -> None:
        self.by_state[state] = self.by_state.get(state, 0) + 1


class BudgetExhausted(Exception):
    pass


class Backfill:
    def __init__(
        self,
        client: PoliteClient,
        store: bronze.BronzeStore,
        manifest: bronze.Manifest,
        *,
        sources: Iterable[Source],
        today: date,
        settle_days: int = DEFAULT_SETTLE_DAYS,
        refresh: bool = False,
        max_requests: int | None = None,
    ) -> None:
        self.client = client
        self.store = store
        self.manifest = manifest
        # The results page always runs first: every other source depends on it.
        others = [s for s in sources if s is not RESULTADOS]
        self.sources = [RESULTADOS, *others]
        self.today = today
        self.settle_days = settle_days
        self.refresh = refresh
        self.max_requests = max_requests
        self.stats = RunStats()

    def run(self, start: date, end: date) -> RunStats:
        end = min(end, self.today)  # never ask for a day that has not happened in Uruguay
        try:
            for day in daterange(start, end):
                self.run_day(day)
        except BudgetExhausted:
            logger.info("request budget reached", extra={"max_requests": self.max_requests})
        return self.stats

    def run_day(self, day: date) -> None:
        for source in self.sources:
            url = self._url_for(source, day)
            if url is None:
                continue
            existing = self.manifest.get(source.name, day)
            if existing and existing["state"] in bronze.FINAL_STATES and not self.refresh:
                self.stats.skipped += 1
                continue
            self._fetch(source, day, url)

    def _url_for(self, source: Source, day: date) -> str | None:
        """The URL to request, or None when this source has nothing to say for ``day``."""
        if source is RESULTADOS:
            return source.url(day)
        if not source.applies_to(day):
            return None
        results = self.manifest.get(RESULTADOS.name, day)
        if not results or results["state"] != bronze.DRAW or source.game not in results["games"]:
            return None
        if source.kind == "pozos_pdf":
            return results["extra"].get("pozos_url")
        return source.url(day)

    def _fetch(self, source: Source, day: date, url: str) -> None:
        if self.max_requests is not None and self.stats.requests >= self.max_requests:
            raise BudgetExhausted
        self.stats.requests += 1
        now = datetime.now(UTC).isoformat(timespec="seconds")
        try:
            result = self.client.get(url)
        except FetchError as exc:
            self._record(bronze.Record(source.name, day, url, bronze.ERROR, now, detail=str(exc)))
            return

        verdict = self._classify(source, day, result.status, result.content)
        state = self._state_for(source, day, verdict)
        key = None
        if state == bronze.DRAW:
            key = self.store.key(source.name, day, source.extension)
            self.store.write(key, result.content)
        self._record(
            bronze.Record(
                source=source.name,
                draw_date=day,
                url=url,
                state=state,
                fetched_at=result.fetched_at.isoformat(timespec="seconds"),
                http_status=result.status,
                games=verdict.games,
                warnings=verdict.warnings,
                extra=verdict.extra,
                detail=verdict.detail,
                content=result.content,
                bronze_key=key,
                content_type=result.headers.get("Content-Type"),
                last_modified=result.headers.get("Last-Modified"),
                classifier_version=classify.CLASSIFIER_VERSION,
            )
        )

    @staticmethod
    def _classify(source: Source, day: date, status: int, content: bytes):
        if source.kind in ("extracto_pdf", "pozos_pdf"):
            return classify.classify_pdf(status, content)
        if status != 200:
            return classify.Classification(classify.ERROR, detail=f"HTTP {status}")
        if source is RESULTADOS:
            return classify.classify_resultados(content, day)
        return classify.classify_extracto_php(content, day)

    def _state_for(self, source: Source, day: date, verdict) -> str:
        if verdict.outcome == classify.DRAW:
            return bronze.DRAW
        if verdict.outcome == classify.ERROR:
            return bronze.ERROR
        if (self.today - day).days < self.settle_days:
            return bronze.NOT_YET_PUBLISHED
        # Per-game sources are only requested when the results page lists the game, so an
        # empty one is a hole in that source, not a day off.
        return bronze.NO_DRAW if source is RESULTADOS else bronze.MISSING

    def _record(self, rec: bronze.Record) -> None:
        self.manifest.record(rec)
        self.stats.count(rec.state)
        if rec.state in (bronze.ERROR, bronze.MISSING) or rec.warnings:
            logger.warning(
                "needs attention",
                extra={
                    "source": rec.source,
                    "draw_date": rec.draw_date.isoformat(),
                    "state": rec.state,
                    "detail": rec.detail,
                    "warnings": list(rec.warnings),
                },
            )


def resolve_sources(spec: str) -> list[Source]:
    chosen: list[Source] = []
    for token in (t.strip() for t in spec.split(",") if t.strip()):
        group = SOURCE_GROUPS.get(token) or (
            (ALL_SOURCES[token],) if token in ALL_SOURCES else None
        )
        if group is None:
            valid = sorted({*SOURCE_GROUPS, *ALL_SOURCES})
            raise argparse.ArgumentTypeError(f"unknown source {token!r}; choose from {valid}")
        chosen.extend(s for s in group if s not in chosen)
    return chosen


def parse_day(value: str) -> date:
    if value == "today":
        return today_in_uruguay()
    return date.fromisoformat(value)


def format_report(manifest: bronze.Manifest) -> str:
    lines = [f"{'source':32} {'state':18} {'count':>7}"]
    for source, state, count in manifest.summary():
        lines.append(f"{source:32} {state:18} {count:>7}")
    for source in ALL_SOURCES:
        span = manifest.date_range(source)
        if span:
            lines.append(f"{source}: draws from {span[0]} to {span[1]}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m loteria_uy.backfill",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--start", type=parse_day, default=DEFAULT_START)
    p.add_argument("--end", type=parse_day, default=None, help="inclusive; default today (UY)")
    p.add_argument(
        "--sources",
        default="resultados,extractos",
        help="comma list of groups (resultados, extractos, pdf, pozos) or names",
    )
    p.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    p.add_argument("--settle-days", type=int, default=DEFAULT_SETTLE_DAYS)
    p.add_argument("--max-requests", type=int, default=None)
    p.add_argument("--refresh", action="store_true", help="re-fetch days already final")
    p.add_argument("--report", action="store_true", help="print the manifest summary and exit")
    return p


def main(argv: list[str] | None = None, *, client: PoliteClient | None = None) -> int:
    args = build_parser().parse_args(argv)
    from loteria.common.logging_setup import configure_logging

    configure_logging("loteria-uy-backfill")
    manifest = bronze.Manifest(args.root / "manifest.sqlite")
    try:
        if not args.report:
            today = today_in_uruguay()
            job = Backfill(
                client or PoliteClient(),
                bronze.BronzeStore(args.root),
                manifest,
                sources=resolve_sources(args.sources),
                today=today,
                settle_days=args.settle_days,
                refresh=args.refresh,
                max_requests=args.max_requests,
            )
            stats = job.run(args.start, args.end or today)
            logger.info(
                "backfill finished",
                extra={"requests": stats.requests, "skipped": stats.skipped, **stats.by_state},
            )
        print(format_report(manifest), file=sys.stderr)
    finally:
        manifest.close()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
