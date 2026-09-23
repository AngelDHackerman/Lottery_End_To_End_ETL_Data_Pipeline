"""Canary: does loteria.org.gt still look the way the extractor expects? (PR-031)

Every other test in this repo runs against captured fixtures, which means they keep passing
forever while the real site quietly changes its markup underneath them. This is the one test
that looks at the live page.

The extractor navigates the site with **six CSS selectors and regexes**. Each is a silent
dependency on someone else's HTML: when the site's authors change a class name, nothing here
breaks until the Thursday 18:00 UTC run fails in production, and the failure surfaces as a
generic ``ValueError`` from deep inside ``extract_lottery_data``. This test asserts the same
six locators against the live page one day earlier, so the alert says "the site changed" and
names the selector, instead of "the Lambda errored".

**It is skipped by default.** Running it costs a scrape.do request against a free-tier quota,
needs a token, and fails whenever the site is behind its Cloudflare waiting room. None of
that should break a local `pytest` or a PR build. ``tests/conftest.py`` skips anything marked
``integration`` unless ``RUN_LIVE_SCRAPER=1``.

Note what this test deliberately does NOT do: import ``loteria.extractor.scraping``. That
module calls ``get_secrets()`` at import time (Secrets Manager) and reads the token from
there. The canary takes its token from the environment instead, so it can run in GitHub
Actions with no AWS credentials at all. The cost of that independence is that the selectors
are written out twice — which ``test_selectors_match_the_extractor`` then guards against,
offline.
"""

from __future__ import annotations

import os
import re
import urllib.parse
from pathlib import Path

import pytest

requests = pytest.importorskip("requests")
bs4 = pytest.importorskip("bs4")
from bs4 import BeautifulSoup  # noqa: E402

AWARD_URL = "https://loteria.org.gt/site/award"
BASE_PROXY_URL = "http://api.scrape.do/"

# PR-031.1: the canary must take the SAME proxy path as the extractor or it stops being a
# canary. All three parameters are required together to get past Cloudflare — see the long
# note in scraping.py. Keep in sync with GEO_CODE / PROXY_RENDER / PROXY_SUPER there.
GEO_CODE = "GT"  # Guatemala; only available on residential (super=true)
PROXY_RENDER = "true"
PROXY_SUPER = "true"

SCRAPING_SRC = Path(__file__).parents[2] / "src" / "loteria" / "extractor" / "scraping.py"

# The six locators `extract_lottery_data` depends on, copied from scraping.py. Each entry is
# (label, literal-as-it-appears-in-the-source). test_selectors_match_the_extractor asserts
# every literal is still present in that file, so a scraper edit cannot leave the canary
# watching a selector nothing uses any more.
EXTRACTOR_LOCATORS = {
    "sorteo link": "div.container a[href*='id=']",
    "header block": "div.heading_s1.text-center",
    # PR-031.1: was "div.card-body div.row", read positionally as [2]. The site moved the
    # prize list into its own named container and left three rows of unrelated content
    # behind, so the old locator kept passing while pointing at boilerplate.
    "prize list": "div.lista-premios-columnas",
    "sorteo number regex": r"SORTEO.*?NO\.?\s+(\d+)",
    # PR-035.1 B: anchored to a full dd/mm/yyyy, so the canary now also fails on a date the
    # extractor would file under year=unknown, not only on a missing label.
    "fecha regex": r"FECHA DEL SORTEO:\s*\d{2}/\d{2}/(\d{4})\b",
}

# The waiting room answers HTTP 200 with a queue page, which is why PR-026's status-code
# metric cannot see it (see that PR's notes). Detecting it here is the difference between
# "the site changed its markup" and "we were queued" — very different actions.
WAITING_ROOM_MARKERS = ("waiting room", "just a moment", "cf-browser-verification")

# PR-031.1: a hard WAF block is NOT the waiting room and must not be skipped like one. The
# waiting room clears by itself; a block page means the proxy profile has stopped working
# and someone has to change it (see scraping.py's GEO_CODE note). Skipping this would be
# the canary going quiet exactly when it has something to say.
BLOCKED_MARKERS = ("you have been blocked", "attention required", "error 1020")


class ProxyRequestFailed(RuntimeError):
    """A scrape.do request that never got a response, with the token scrubbed out."""


def redact(text: str, token: str) -> str:
    """Replace every occurrence of the token with ``***``."""
    return text.replace(token, "***") if token else text


def fetch(url: str, token: str) -> requests.Response:
    """Fetch through scrape.do, the same proxy profile the extractor uses.

    ⚠️ THE TRY/EXCEPT IS A CREDENTIAL CONTROL, NOT ERROR HANDLING. scrape.do takes its token
    as a **query parameter**, so the token sits in `proxy_url` in cleartext — and every
    ``requests`` exception embeds the URL it was trying to reach. A plain ConnectionError
    therefore carries the live token in its message, pytest prints that traceback, and the
    workflow around this file pipes the output to a file it later posts into a GitHub issue.
    On a public repo that publishes the token to the world.

    So: catch, scrub, re-raise. ``from None`` is load-bearing — with ``from exc`` (or no
    ``from`` at all) Python still prints the original exception under "During handling of the
    above exception...", token and all, and the scrubbing would achieve nothing.

    Successful responses need no such care: the token is not echoed in the body, and
    ``resp.url`` is only reachable from code that goes looking for it.

    The two concerns meet in the timeout below, and they pull the same way. PR-031.1 raised
    it to 60 s so a proxy failure surfaces as the real 502 instead of an anonymous local
    ReadTimeout — and an anonymous timeout is also the exception shape most likely to be
    dumped straight into an issue body. A clearer error and a scrubbed one are the same fix.
    """
    proxy_url = (
        f"{BASE_PROXY_URL}?url={urllib.parse.quote(url, safe='')}"
        f"&token={token}&geoCode={GEO_CODE}"
        f"&render={PROXY_RENDER}&super={PROXY_SUPER}"
    )
    # 60 s, matching scraping.py: a rendered success returns in ~5-6 s but scrape.do itself
    # takes ~57 s to give up, and cutting below that hides the real error behind a timeout.
    # Do NOT lower this to make the canary faster — PR-031.1 exists because it was 25 s.
    try:
        return requests.get(proxy_url, timeout=60)
    except requests.RequestException as exc:
        raise ProxyRequestFailed(
            f"{type(exc).__name__} reaching scrape.do for {url}: {redact(str(exc), token)}"
        ) from None


# ==========================================================================================
# Offline guard — runs in every CI build, no network
# ==========================================================================================
def test_selectors_match_the_extractor():
    """The canary's locators must still exist in scraping.py.

    Without this, the realistic failure is silent: someone updates a selector in the
    extractor to follow a site change, the canary keeps asserting the OLD selector against
    the live page, and it either fails for the wrong reason or — worse — passes while
    watching something the pipeline no longer uses.

    Not marked `integration`: it reads a local file, so it runs everywhere.
    """
    source = SCRAPING_SRC.read_text(encoding="utf-8")

    missing = [
        f"{label}: {literal!r}"
        for label, literal in EXTRACTOR_LOCATORS.items()
        if literal not in source
    ]
    assert not missing, (
        "These locators are asserted by the canary but no longer appear in "
        f"{SCRAPING_SRC.name} — update both together:\n  " + "\n  ".join(missing)
    )


# ==========================================================================================
# Offline guard — the token must never reach a log
# ==========================================================================================
# Deliberately UNMARKED, like the selector guard above: it needs no network and no token, so
# it runs in every CI build. A leak control that only runs on Wednesdays is not a control.
FAKE_TOKEN = "s3cr3t-t0ken-value"  # nosec B105 - not a real credential


def _rendered_traceback(exc: BaseException) -> str:
    """The exception exactly as pytest would print it, chained causes included."""
    import traceback

    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))


class TestTokenIsNeverLeaked:
    """scrape.do authenticates by query parameter, so the token is in every request URL.

    The path that made this urgent: a connection error embeds that URL in its message ->
    pytest prints the traceback -> the workflow pipes stdout through `tee canary.log` ->
    the failure handler posts the tail of that file into a GitHub issue -> this repo is
    PUBLIC. GitHub masks secrets in the Actions log view, but `tee` writes the raw bytes to
    disk and the issue body is built from the file, not from the masked stream.

    Observed for real on 2026-08-15: a local run failed with a ConnectionError whose message
    contained the live token in full.
    """

    @staticmethod
    def _raise_connection_error(*_args, **_kwargs):
        raise requests.ConnectionError(
            "HTTPConnectionPool(host='api.scrape.do', port=80): Max retries exceeded with "
            f"url: /?url=https%3A%2F%2Floteria.org.gt&token={FAKE_TOKEN}&geoCode=MX"
        )

    def test_redact_replaces_every_occurrence(self):
        assert redact(f"a {FAKE_TOKEN} b {FAKE_TOKEN}", FAKE_TOKEN) == "a *** b ***"

    def test_redact_tolerates_an_empty_token(self):
        """The token fixture skips on an empty value, but redact() must not turn "" into a
        match that replaces every character boundary in the string."""
        assert redact("nothing to hide", "") == "nothing to hide"

    def test_a_connection_error_does_not_carry_the_token(self, monkeypatch):
        monkeypatch.setattr(requests, "get", self._raise_connection_error)

        with pytest.raises(ProxyRequestFailed) as excinfo:
            fetch(AWARD_URL, FAKE_TOKEN)

        assert FAKE_TOKEN not in str(excinfo.value)

    def test_the_original_exception_is_suppressed(self, monkeypatch):
        """`from None` is what stops Python printing the untouched original under "During
        handling of the above exception". Without it the scrubbing is cosmetic."""
        monkeypatch.setattr(requests, "get", self._raise_connection_error)

        with pytest.raises(ProxyRequestFailed) as excinfo:
            fetch(AWARD_URL, FAKE_TOKEN)

        assert excinfo.value.__cause__ is None
        assert excinfo.value.__suppress_context__ is True

    def test_the_rendered_traceback_is_clean(self, monkeypatch):
        """The one that actually matters: format the exception the way pytest does and check
        the whole thing, not just the message."""
        monkeypatch.setattr(requests, "get", self._raise_connection_error)

        with pytest.raises(ProxyRequestFailed) as excinfo:
            fetch(AWARD_URL, FAKE_TOKEN)

        assert FAKE_TOKEN not in _rendered_traceback(excinfo.value)

    def test_the_failure_still_says_what_broke(self, monkeypatch):
        """Scrubbing must not cost the diagnosis. The message keeps the exception type and
        the target URL, which is what distinguishes "no network" from "site moved"."""
        monkeypatch.setattr(requests, "get", self._raise_connection_error)

        with pytest.raises(ProxyRequestFailed) as excinfo:
            fetch(AWARD_URL, FAKE_TOKEN)

        message = str(excinfo.value)
        assert "ConnectionError" in message
        assert AWARD_URL in message
        assert "***" in message

    def test_a_timeout_is_scrubbed_too(self, monkeypatch):
        """Not just ConnectionError — every requests exception embeds the URL, so the except
        clause has to catch the base class."""

        def _timeout(*_args, **_kwargs):
            raise requests.Timeout(f"timed out for /?token={FAKE_TOKEN}")

        monkeypatch.setattr(requests, "get", _timeout)

        with pytest.raises(ProxyRequestFailed) as excinfo:
            fetch(AWARD_URL, FAKE_TOKEN)

        assert FAKE_TOKEN not in _rendered_traceback(excinfo.value)


# ==========================================================================================
# Live contract — opt-in
# ==========================================================================================
@pytest.fixture(scope="module")
def token() -> str:
    tok = os.environ.get("SCRAPE_DO_TOKEN")
    if not tok:
        pytest.skip("SCRAPE_DO_TOKEN not set")
    return tok


@pytest.fixture(scope="module")
def award_page(token) -> BeautifulSoup:
    """The awards index, fetched once for the whole module.

    Module-scoped on purpose: the free-tier quota is the scarce resource here, so the suite
    spends two requests total (this page plus one sorteo page), not one per assertion.
    """
    resp = fetch(AWARD_URL, token)

    if resp.status_code != 200:
        pytest.fail(
            f"scrape.do returned HTTP {resp.status_code} for {AWARD_URL}. "
            "401/402/429 mean the free tier lapsed, the quota is spent, or we are rate "
            "limited — that is a proxy problem, not a site-layout problem."
        )

    lowered = resp.text.lower()
    if any(marker in lowered for marker in BLOCKED_MARKERS):
        pytest.fail(
            "Cloudflare served a hard block page for loteria.org.gt. The render+super+GT "
            "proxy profile has stopped working — this needs a new profile, not a retry. "
            "See docs/runbooks/PR-031.1-scraper-restore.md."
        )

    if any(marker in lowered for marker in WAITING_ROOM_MARKERS):
        pytest.skip(
            "loteria.org.gt is behind its Cloudflare waiting room (HTTP 200 with a queue "
            "page). Not a contract break — retry later."
        )

    return BeautifulSoup(resp.content, "html.parser")


@pytest.mark.integration
class TestAwardPageContract:
    def test_has_at_least_one_sorteo_link(self, award_page):
        """`div.container a[href*='id=']` — how the extractor finds the latest sorteo.

        This is the selector that broke on 2026-07-19/20: the waiting-room page has no such
        link, and the extractor's error was an unhelpful "No se pudo encontrar el enlace".
        """
        links = award_page.select(EXTRACTOR_LOCATORS["sorteo link"])
        assert links, "no sorteo links found — the awards index layout changed"

    def test_sorteo_link_carries_a_numeric_id(self, award_page):
        from urllib.parse import parse_qs, urlparse

        href = award_page.select_one(EXTRACTOR_LOCATORS["sorteo link"])["href"]
        url = href if href.startswith("http") else f"https://loteria.org.gt{href}"
        lottery_id = parse_qs(urlparse(url).query).get("id", [None])[0]

        assert lottery_id and lottery_id.isdigit(), f"unexpected sorteo href: {href!r}"


@pytest.fixture(scope="module")
def sorteo_page(award_page, token) -> BeautifulSoup:
    """The latest sorteo's own page — the second and last request this suite makes.

    Module-scoped and defined at module level (not inside the class): pytest deprecates
    class-scoped fixtures written as instance methods, and module scope is what keeps this to
    one request no matter how many assertions read it.
    """
    href = award_page.select_one(EXTRACTOR_LOCATORS["sorteo link"])["href"]
    url = href if href.startswith("http") else f"https://loteria.org.gt{href}"
    resp = fetch(url, token)

    if resp.status_code != 200:
        pytest.fail(f"scrape.do returned HTTP {resp.status_code} for {url}")

    return BeautifulSoup(resp.content, "html.parser")


@pytest.mark.integration
class TestSorteoPageContract:
    def test_h2_matches_the_sorteo_number_regex(self, sorteo_page):
        """The extractor derives `numero_sorteo` — the Silver partition key — from this."""
        h2 = sorteo_page.find("h2")
        assert h2 is not None, "no <h2> on the sorteo page"

        match = re.search(EXTRACTOR_LOCATORS["sorteo number regex"], h2.text.strip(), re.IGNORECASE)
        assert match, f"h2 no longer matches the SORTEO regex: {h2.text.strip()!r}"
        assert int(match.group(1)) > 0

    def test_header_block_exists_and_carries_the_fecha(self, sorteo_page):
        """`div.heading_s1.text-center` becomes the HEADER section of the raw .txt.

        The fecha matters twice over: it is the only source of the `year` partition, and
        `transform()` raises rather than guess when it cannot be parsed.
        """
        header = sorteo_page.select_one(EXTRACTOR_LOCATORS["header block"])
        assert header is not None, "header block missing — HEADER would be written empty"

        text = " ".join(line.strip() for line in header.get_text("\n").split("\n") if line.strip())
        assert re.search(
            EXTRACTOR_LOCATORS["fecha regex"], text
        ), f"no 'FECHA DEL SORTEO:' in the header block: {text[:200]!r}"

    def test_prize_list_container_exists(self, sorteo_page):
        """`div.lista-premios-columnas` becomes the BODY section of the raw .txt.

        PR-031.1 replaced a positional index (`div.card-body div.row` read as `[2]`) with
        this named container. The index was the most fragile locator in the pipeline and it
        did fail exactly as feared: the site inserted content, the prizes moved, and the old
        selector went on returning a div full of legal boilerplate.
        """
        container = sorteo_page.select_one(EXTRACTOR_LOCATORS["prize list"])
        assert container is not None, (
            f"{EXTRACTOR_LOCATORS['prize list']} missing — the prize list has moved again "
            "and the extractor would write a BODY with no prizes in it"
        )

    def test_prize_list_actually_looks_like_prize_data(self, sorteo_page):
        """Guards the container above: existing is not the same as holding the prizes.

        This is the assertion that would have caught the 2026-08 redesign a day early. A
        prize line looks like `00046 P .... 700.00`; the rendered page pads the fields with
        runs of whitespace, which `\\s+` absorbs here exactly as it does in parser.py:89.
        """
        container = sorteo_page.select_one(EXTRACTOR_LOCATORS["prize list"])
        body = container.get_text("\n")

        prize_lines = re.findall(r"\d+\s+\w+\s+\.+\s+[\d,]+\.?\d*", body)
        assert len(prize_lines) >= 10, (
            f"{EXTRACTOR_LOCATORS['prize list']} holds {len(prize_lines)} prize-shaped "
            "lines; the prize list has probably moved to a different container"
        )
