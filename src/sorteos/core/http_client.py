"""The only door ``sorteos`` has to the network (UY-001).

Three properties, each enforced here so no caller can forget them:

1. **Privacy blocklist.** Every client is built with the URL patterns it must never touch,
   and there is no default: a country with nothing to hide passes ``blocklist=()`` out
   loud. The patterns themselves live with each country, in code and never in a YAML
   (``sorteos.uy.privacy``; DESIGN.md, P5). A match is never requested, followed through a
   redirect, stored or logged. The check runs BEFORE a socket is opened, against the
   percent-decoded URL, case-insensitively, and again on every redirect hop (redirects are
   followed by hand for exactly that reason). A blocked URL is logged by pattern only,
   never by its full text.
2. **Courtesy.** One request per second across every client in the process, an
   identifiable User-Agent, exponential backoff with jitter on 429/5xx and on transport
   errors, ``Retry-After`` honoured. A POST (a search form, UY-030.2) gets all of it too: it
   is retried like a GET, so only a form that reads, never one that changes anything, may
   be sent through here.
3. **No caching here.** What has already been fetched is the manifest's business
   (manifest.Manifest) — a ``no_draw`` day is never stored in bronze but must not be fetched
   again either, so the cache cannot be the raw store (roadmap-uruguay.md, C3).

The User-Agent names the caller's ``agent`` (a ``product/version`` token each country picks,
since it is how that site knows us) and a contact that defaults to the repository URL, not a
personal address.
"""

from __future__ import annotations

import logging
import random
import re
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import unquote, urljoin

import requests

logger = logging.getLogger(__name__)

DEFAULT_CONTACT = "https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline"
USER_AGENT_TEMPLATE = "{agent} (data-engineering portfolio; +{contact})"

RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
MAX_REDIRECTS = 5
REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
KEEP_METHOD_STATUSES = frozenset({307, 308})  # a POST stays a POST; the rest go on as GET


class BlockedURLError(RuntimeError):
    """Raised instead of fetching a URL that matches the privacy blocklist."""

    def __init__(self, pattern: str) -> None:
        # The message names the pattern, never the URL: the URL itself identifies the file.
        super().__init__(f"refusing a URL matching the privacy blocklist ({pattern})")
        self.pattern = pattern


class FetchError(RuntimeError):
    """The request could not be completed after every retry."""


def checked_blocklist(blocklist: Sequence[str]) -> tuple[str, ...]:
    """Validate a blocklist and return it upper-cased.

    A bare string is refused rather than iterated: ``"DET_INVALIDAS"`` would otherwise turn
    into thirteen one-letter patterns. An empty pattern would match every URL.
    """
    if isinstance(blocklist, str):
        raise TypeError("blocklist is a sequence of patterns, not a single string")
    patterns = tuple(blocklist)
    for pattern in patterns:
        if not isinstance(pattern, str) or not pattern.strip():
            raise ValueError(f"blocklist patterns must be non-empty strings, got {pattern!r}")
    return tuple(p.upper() for p in patterns)


def blocked_pattern(url: str, blocklist: Sequence[str]) -> str | None:
    """Return the pattern of ``blocklist`` that ``url`` matches, or None.

    Decoded repeatedly so ``%5F`` / ``%255F`` tricks cannot hide an underscore, and compared
    upper-case because a site may serve the same file as ``.PDF`` and ``.pdf``.
    """
    text = url
    for _ in range(3):
        decoded = unquote(text)
        if decoded == text:
            break
        text = decoded
    upper = text.upper()
    for pattern in checked_blocklist(blocklist):
        if pattern in upper:
            return pattern
    return None


def assert_allowed(url: str, blocklist: Sequence[str]) -> None:
    pattern = blocked_pattern(url, blocklist)
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
        blocklist: Sequence[str],
        agent: str,
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
        self.blocklist = checked_blocklist(blocklist)
        if not isinstance(agent, str) or not re.fullmatch(r"[\w.-]+/[\w.-]+", agent):
            raise ValueError(f"agent must be a product/version token, got {agent!r}")
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.backoff_cap = backoff_cap
        self.timeout = timeout
        self._sleep = sleep
        self._session = session or requests.Session()
        self.user_agent = USER_AGENT_TEMPLATE.format(
            agent=agent, contact=contact or DEFAULT_CONTACT
        )
        self._session.headers.update({"User-Agent": self.user_agent})

    def get(self, url: str) -> FetchResult:
        """GET ``url`` politely. Returns any final status (callers judge a 404); raises
        FetchError only when retries are exhausted on 429/5xx/transport errors."""
        return self._fetch(url, None)

    def post(self, url: str, data: Mapping[str, str]) -> FetchResult:
        """POST the form ``data`` to ``url``, with everything :meth:`get` does. Only for a
        form that reads: a retry sends it again."""
        return self._fetch(url, dict(data))

    def _fetch(self, url: str, data: dict[str, str] | None) -> FetchResult:
        assert_allowed(url, self.blocklist)
        attempt = 0
        while True:
            try:
                result = self._send_following_redirects(url, data)
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

    def _send_following_redirects(self, url: str, data: dict[str, str] | None) -> FetchResult:
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            assert_allowed(current, self.blocklist)
            _GLOBAL_LIMITER.wait(self.min_interval, sleep=self._sleep)
            started = time.monotonic()
            if data is None:
                response = self._session.get(current, timeout=self.timeout, allow_redirects=False)
            else:
                response = self._session.post(
                    current, data=data, timeout=self.timeout, allow_redirects=False
                )
            elapsed = time.monotonic() - started
            location = response.headers.get("Location")
            if response.status_code in REDIRECT_STATUSES and location:
                current = urljoin(current, location)  # checked by assert_allowed above
                if response.status_code not in KEEP_METHOD_STATUSES:
                    data = None
                continue
            logger.info(
                "fetched",
                extra={
                    "method": "GET" if data is None else "POST",
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
        # Backoff jitter, not cryptography.
        delay += random.uniform(0, delay / 2)  # nosec B311
        if retry_after and re.fullmatch(r"\d+", retry_after.strip()):
            delay = max(delay, min(self.backoff_cap * 5, float(retry_after)))
        logger.warning(
            "retrying",
            extra={"url": url, "reason": reason, "attempt": attempt + 1, "delay_s": delay},
        )
        self._sleep(delay)
