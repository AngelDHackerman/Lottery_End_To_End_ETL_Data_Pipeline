"""The only door this package has to the network (UY-001).

Three properties, each enforced here so no caller can forget them:

1. **Privacy blocklist.** The DNLQ publishes ``*_DET_INVALIDAS_*`` PDFs next to its
   results, and they carry a "Cédula Id." column — national ID numbers tied to voided
   phone bets. Nothing matching ``DET_INVALIDAS`` is requested, followed through a
   redirect, stored or logged. The check runs BEFORE a socket is opened, against the
   percent-decoded URL, case-insensitively, and again on every redirect hop (redirects are
   followed by hand for exactly that reason). A blocked URL is logged by pattern only,
   never by its full text.
2. **Courtesy.** One request per second across every client in the process, an
   identifiable User-Agent, exponential backoff with jitter on 429/5xx and on transport
   errors, ``Retry-After`` honoured.
3. **No caching here.** What has already been fetched is the manifest's business
   (bronze.Manifest) — a ``no_draw`` day is never stored in bronze but must not be fetched
   again either, so the cache cannot be the raw store (roadmap-uruguay.md, C3).

The User-Agent's contact defaults to the repository URL, not a personal address; override
with ``LOTERIA_UY_CONTACT``.
"""

from __future__ import annotations

import logging
import os
import random
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import unquote, urljoin

import requests

logger = logging.getLogger(__name__)

BLOCKED_PATTERNS = ("DET_INVALIDAS",)

DEFAULT_CONTACT = "https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline"
USER_AGENT_TEMPLATE = "loteria-uy-research/0.1 (data-engineering portfolio; +{contact})"

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_REDIRECTS = 5


class BlockedURLError(RuntimeError):
    """Raised instead of fetching a URL that matches the privacy blocklist."""

    def __init__(self, pattern: str) -> None:
        # The message names the pattern, never the URL: the URL itself identifies the file.
        super().__init__(f"refusing a URL matching the privacy blocklist ({pattern})")
        self.pattern = pattern


class FetchError(RuntimeError):
    """The request could not be completed after every retry."""


def blocked_pattern(url: str) -> str | None:
    """Return the blocklist pattern ``url`` matches, or None.

    Decoded repeatedly so ``%5F`` / ``%255F`` tricks cannot hide an underscore, and compared
    upper-case because the site serves the same file as ``.PDF`` and ``.pdf``.
    """
    text = url
    for _ in range(3):
        decoded = unquote(text)
        if decoded == text:
            break
        text = decoded
    upper = text.upper()
    for pattern in BLOCKED_PATTERNS:
        if pattern in upper:
            return pattern
    return None


def assert_allowed(url: str) -> None:
    pattern = blocked_pattern(url)
    if pattern is not None:
        logger.warning("blocked request", extra={"blocked_url_pattern": pattern})
        raise BlockedURLError(pattern)


@dataclass(frozen=True)
class FetchResult:
    url: str  # as requested
    final_url: str  # after redirects
    status: int
    headers: dict = field(repr=False)
    content: bytes = field(repr=False)
    fetched_at: datetime
    elapsed_s: float


class _RateLimiter:
    """A process-wide minimum interval between request starts."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._next_at = 0.0

    def wait(self, min_interval: float, clock=time.monotonic, sleep=time.sleep) -> None:
        with self._lock:
            now = clock()
            if now < self._next_at:
                sleep(self._next_at - now)
                now = clock()
            self._next_at = now + min_interval


# Shared on purpose: two clients in one process must not double the request rate.
_GLOBAL_LIMITER = _RateLimiter()


class PoliteClient:
    def __init__(
        self,
        *,
        min_interval: float = 1.0,
        max_retries: int = 5,
        backoff_base: float = 2.0,
        backoff_cap: float = 120.0,
        timeout: float = 30.0,
        contact: str | None = None,
        session: requests.Session | None = None,
        sleep=time.sleep,
    ) -> None:
        if min_interval < 1.0:
            raise ValueError("min_interval below 1 s breaks the courtesy rule (1 req/s)")
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.backoff_cap = backoff_cap
        self.timeout = timeout
        self._sleep = sleep
        self._session = session or requests.Session()
        contact = contact or os.environ.get("LOTERIA_UY_CONTACT") or DEFAULT_CONTACT
        self.user_agent = USER_AGENT_TEMPLATE.format(contact=contact)
        self._session.headers.update({"User-Agent": self.user_agent})

    def get(self, url: str) -> FetchResult:
        """GET ``url`` politely. Returns any final status (callers judge a 404); raises
        FetchError only when retries are exhausted on 429/5xx/transport errors."""
        assert_allowed(url)
        attempt = 0
        while True:
            try:
                result = self._get_following_redirects(url)
            except BlockedURLError:
                raise
            except requests.RequestException as exc:
                if attempt >= self.max_retries:
                    raise FetchError(f"{type(exc).__name__} after {attempt + 1} attempts") from exc
                self._backoff(attempt, None, reason=type(exc).__name__, url=url)
                attempt += 1
                continue

            if result.status in RETRY_STATUSES:
                if attempt >= self.max_retries:
                    raise FetchError(f"HTTP {result.status} after {attempt + 1} attempts")
                self._backoff(
                    attempt,
                    result.headers.get("Retry-After"),
                    reason=f"HTTP {result.status}",
                    url=url,
                )
                attempt += 1
                continue
            return result

    def _get_following_redirects(self, url: str) -> FetchResult:
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            assert_allowed(current)
            _GLOBAL_LIMITER.wait(self.min_interval, sleep=self._sleep)
            started = time.monotonic()
            response = self._session.get(current, timeout=self.timeout, allow_redirects=False)
            elapsed = time.monotonic() - started
            location = response.headers.get("Location")
            if response.status_code in (301, 302, 303, 307, 308) and location:
                current = urljoin(current, location)  # checked by assert_allowed above
                continue
            logger.info(
                "fetched",
                extra={
                    "url": current,
                    "status": response.status_code,
                    "bytes": len(response.content),
                    "elapsed_s": round(elapsed, 3),
                },
            )
            return FetchResult(
                url=url,
                final_url=current,
                status=response.status_code,
                headers=dict(response.headers),
                content=response.content,
                fetched_at=datetime.now(UTC),
                elapsed_s=elapsed,
            )
        raise requests.TooManyRedirects(f"more than {MAX_REDIRECTS} redirects")

    def _backoff(self, attempt: int, retry_after: str | None, *, reason: str, url: str) -> None:
        delay = min(self.backoff_cap, self.backoff_base * (2**attempt))
        delay += random.uniform(0, delay / 2)
        if retry_after and re.fullmatch(r"\d+", retry_after.strip()):
            delay = max(delay, min(self.backoff_cap * 5, float(retry_after)))
        logger.warning(
            "retrying",
            extra={"url": url, "reason": reason, "attempt": attempt + 1, "delay_s": delay},
        )
        self._sleep(delay)
