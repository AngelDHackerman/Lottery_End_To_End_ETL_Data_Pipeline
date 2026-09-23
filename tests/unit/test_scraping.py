"""Unit tests for ``loteria.extractor.scraping`` (PR-031.1).

Two things broke the pipeline on 2026-08-20, and both were invisible to the existing suite:

1. **The proxy profile.** loteria.org.gt tightened Cloudflare and the old scrape.do request
   (``geoCode=MX``, no render, no super) stopped connecting entirely. The working profile
   needs three parameters together; dropping any one of them is a full outage, so the URL
   builder is worth asserting on.
2. **The prize-list locator.** The site moved the prizes into a new container and left three
   unrelated rows behind, so the old positional selector kept "working" and would have
   written prize-less files. Nothing failed — that is what makes it dangerous.

``scraping.py`` calls ``get_secrets()`` at MODULE scope, so importing it normally reaches
Secrets Manager. ``scraping_module`` below patches that away and imports under the patch,
which is the same trick ``tests/conftest.py`` uses for the ``awsglue`` stub.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

requests = pytest.importorskip("requests")
pytest.importorskip("bs4")
from bs4 import BeautifulSoup  # noqa: E402

FIXTURE = Path(__file__).parents[1] / "fixtures" / "sorteo_page_2026_08.html"

FAKE_SECRETS = {
    "partitioned": "test-partitioned-bucket",
    "scrape_do_token": "test-token-123",
}


@pytest.fixture(scope="module")
def scraping_module():
    """Import ``loteria.extractor.scraping`` with Secrets Manager patched out.

    The module reads its token and bucket names at import time, so the patch has to wrap the
    import itself, not just the call. Popping any cached copy first matters when another
    test module has already imported it with different fakes.
    """
    sys.modules.pop("loteria.extractor.scraping", None)

    with patch("loteria.common.aws_secrets.get_secrets", return_value=FAKE_SECRETS):
        module = importlib.import_module("loteria.extractor.scraping")

    yield module

    sys.modules.pop("loteria.extractor.scraping", None)


@pytest.fixture(scope="module")
def sorteo_soup() -> BeautifulSoup:
    return BeautifulSoup(FIXTURE.read_text(encoding="utf-8"), "html.parser")


# ==========================================================================================
# The proxy profile
# ==========================================================================================
class TestBuildProxyUrl:
    """All three Cloudflare-bypass parameters must be on every request.

    Tested individually rather than as one string comparison so a failure names the missing
    parameter instead of dumping two near-identical URLs to compare by eye.
    """

    def test_targets_guatemala(self, scraping_module):
        url = scraping_module.build_proxy_url("https://loteria.org.gt/site/award")
        assert "geoCode=GT" in url

    def test_requests_headless_rendering(self, scraping_module):
        """Without render=true the request fails Cloudflare's browser check."""
        url = scraping_module.build_proxy_url("https://loteria.org.gt/site/award")
        assert "render=true" in url

    def test_requests_residential_ips(self, scraping_module):
        """Without super=true, geoCode=GT is not even available — GT is residential-only."""
        url = scraping_module.build_proxy_url("https://loteria.org.gt/site/award")
        assert "super=true" in url

    def test_target_url_is_encoded(self, scraping_module):
        """The target carries its own query string; unencoded it would be parsed as
        parameters of the scrape.do call instead."""
        url = scraping_module.build_proxy_url(
            "https://loteria.org.gt/site/award-detail?id=291&sorteo=3133"
        )
        assert "url=https%3A%2F%2Floteria.org.gt%2Fsite%2Faward-detail%3Fid%3D291" in url
        # The target's own '&sorteo=' must not survive as a top-level separator.
        assert "&sorteo=3133" not in url

    def test_token_is_included(self, scraping_module):
        assert "token=test-token-123" in scraping_module.build_proxy_url("https://example.com")

    def test_timeout_stays_above_the_proxy_give_up(self, scraping_module):
        """scrape.do itself takes ~57 s to return ROTATION_FAILED.

        The pre-PR-031.1 value of 25 s meant production never saw that error — only a local
        ReadTimeout — which is why the outage was misdiagnosed for two weeks. Must also
        leave room for a second call inside the Lambda's 120 s ceiling.
        """
        assert 58 <= scraping_module.PROXY_TIMEOUT <= 110


# ==========================================================================================
# Telemetry on the failure paths
# ==========================================================================================
class TestFetchViaProxyTelemetry:
    def test_timeout_emits_a_metric_and_re_raises(self, scraping_module):
        """The regression that kept ScrapeDo_Failed green through a two-week outage.

        ``record_scraper_status`` needs a response object, so the timeout path emitted
        nothing at all and the alarm had no datapoint to fire on.
        """
        with (
            patch.object(
                scraping_module.requests, "get", side_effect=requests.exceptions.ReadTimeout()
            ),
            patch.object(scraping_module, "record_scraper_no_response") as no_response,
        ):
            with pytest.raises(requests.exceptions.ReadTimeout):
                scraping_module.fetch_via_proxy("https://loteria.org.gt/site/award")

        no_response.assert_called_once()
        # The exception class name is what tells a reader whether it was a connect or a
        # read failure.
        assert no_response.call_args[0][0] == "ReadTimeout"

    def test_non_200_still_emits_the_status_metric(self, scraping_module):
        """PR-026 behaviour, re-asserted here so PR-031.1's try/except cannot regress it."""
        response = requests.Response()
        response.status_code = 429
        response._content = b"rate limited"

        with (
            patch.object(scraping_module.requests, "get", return_value=response),
            patch.object(scraping_module, "record_scraper_status") as status,
        ):
            with pytest.raises(ValueError):
                scraping_module.fetch_via_proxy("https://loteria.org.gt/site/award")

        status.assert_called_once_with(429)

    def test_success_returns_the_response(self, scraping_module):
        response = requests.Response()
        response.status_code = 200
        response._content = b"<html></html>"

        with (
            patch.object(scraping_module.requests, "get", return_value=response),
            patch.object(scraping_module, "record_scraper_status"),
        ):
            assert scraping_module.fetch_via_proxy("https://loteria.org.gt") is response


# ==========================================================================================
# The prize-list locator
# ==========================================================================================
class TestExtractPrizeBody:
    def test_reads_the_prize_container(self, scraping_module, sorteo_soup):
        body = scraping_module.extract_prize_body(sorteo_soup)
        assert "01605 P .... 1,000,000.00" in body

    def test_collapses_the_rendered_whitespace_padding(self, scraping_module, sorteo_soup):
        """Keeps new raw files shaped like the 110 already in S3.

        The rendered page emits `00068        TT        .... 800.00`; the archive uses
        single spaces. parser.py tolerates both, but a mixed archive is a trap for anyone
        reprocessing it later.
        """
        body = scraping_module.extract_prize_body(sorteo_soup)

        assert "00068 TT .... 800.00" in body
        assert "  " not in body, "double spaces survived the collapse"

    def test_keeps_vendedor_lines(self, scraping_module, sorteo_soup):
        """`VENDIDO POR` lines attach a winner to the prize above them (parser.py:108).

        Dropping them would silently empty the vendor columns that gold_vendor_leaderboard
        and gold_geo_winnings are built from.
        """
        body = scraping_module.extract_prize_body(sorteo_soup)
        assert "VENDIDO POR PERSONA DE PRUEBA UNO" in body

    def test_keeps_section_labels(self, scraping_module, sorteo_soup):
        """Labels like MIL match no parser branch and are skipped — but they are part of the
        archived raw format, so their loss would be a silent format change."""
        body = scraping_module.extract_prize_body(sorteo_soup)
        assert "MIL" in body.split("\n")

    def test_rejects_a_page_without_the_container(self, scraping_module):
        """The site moving the prizes again must fail loudly, not write an empty BODY."""
        soup = BeautifulSoup(
            "<html><body><div class='card-body'></div></body></html>", "html.parser"
        )

        with pytest.raises(ValueError, match="lista-premios-columnas"):
            scraping_module.extract_prize_body(soup)

    def test_rejects_a_container_without_prize_lines(self, scraping_module):
        """THE regression test for the 2026-08 redesign.

        The failure mode was not a crash: the container existed and yielded text, it just
        was not the prize list. Anything that only checks "did we find an element" passes
        here — the guard has to look at the content.
        """
        soup = BeautifulSoup(
            "<div class='lista-premios-columnas'>ESTIMADO PUBLICO. Para cambiar sus "
            "billetes premiados deberá presentar su DPI.</div>",
            "html.parser",
        )

        with pytest.raises(ValueError, match="líneas de premio"):
            scraping_module.extract_prize_body(soup)

    def test_the_old_positional_selector_would_have_passed_silently(
        self, scraping_module, sorteo_soup
    ):
        """Documents why this PR exists, against the real post-redesign shape.

        The pre-PR-031.1 code took `div.card-body div.row` and read index [2] after checking
        `len(rows) >= 3`. On the current page that check still passes and index [2] still
        returns text — boilerplate, with no prize lines in it. The extractor would have
        uploaded that as the sorteo's BODY and the Step Function would have gone green.
        """
        rows = sorteo_soup.select("div.card-body div.row")
        assert len(rows) >= 3, "fixture must keep the trap intact"

        old_body = rows[2].get_text("\n")
        assert "ESTIMADO PUBLICO" in old_body

        import re

        assert re.findall(r"\d+\s+\w+\s+\.+\s+[\d,]+\.?\d*", old_body) == []
