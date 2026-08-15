"""Tests for the extractor: the scrape.do proxy call and the page parsing (PR-035).

``loteria.extractor.scraping`` was the largest untested module in the project and the one
with the most ways to fail quietly. It calls ``get_secrets()`` at **import** time, so — like
the transformer in PR-030 — it has to be imported through a fixture that neutralises that
first.

The HTML fixtures here are minimal by design. They are not a copy of loteria.org.gt: the
job of pinning the real selectors belongs to PR-031's live canary, which hits the actual
site weekly. What these tests pin is what the extractor *does* with a page once it has one —
which branch it takes, what it writes, and where it uploads it. Those are the parts a live
test cannot check without polluting prod.
"""

from __future__ import annotations

import importlib
import sys

import boto3
import pytest
from moto import mock_aws

REGION = "us-east-1"
PARTITIONED = "test-partitioned-bucket"
SIMPLE = "test-simple-bucket"
TOKEN = "test-token"


# ==========================================================================================
# Page fixtures
# ==========================================================================================
AWARD_PAGE = """
<html><body>
  <div class="container">
    <a href="/site/awardDetail?id=999">Sorteo Ordinario No. 3046</a>
    <a href="/site/awardDetail?id=998">Sorteo Ordinario No. 3045</a>
  </div>
</body></html>
"""

DETAIL_PAGE = """
<html><body>
  <h2>  SORTEO   ORDINARIO NO. 3046  </h2>
  <div class="heading_s1 text-center">
    SORTEO ORDINARIO NO. 3046

    FECHA DEL SORTEO: 01/06/2024
    FECHA DE CADUCIDAD: 30/08/2024
    PRIMER PREMIO 12345 ||| SEGUNDO PREMIO 2222 ||| TERCER PREMIO 4444
    REINTEGROS 5, 2, 4
  </div>
  <div class="card-body">
    <div class="row">nav</div>
    <div class="row">filters</div>
    <div class="row">
      00MIL
      12345 P ....... 1,000,000.00
      VENDIDO POR UN VENDEDOR, ANTIGUA, SACATEPEQUEZ
    </div>
  </div>
</body></html>
"""


class FakeResponse:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.content = text.encode("utf-8")
        self.status_code = status_code


# ==========================================================================================
# Fixtures
# ==========================================================================================
@pytest.fixture
def s3():
    with mock_aws():
        client = boto3.client("s3", region_name=REGION)
        client.create_bucket(Bucket=PARTITIONED)
        client.create_bucket(Bucket=SIMPLE)
        yield client


@pytest.fixture
def scraping(monkeypatch):
    """Import the module with its import-time Secrets Manager call neutralised.

    Same shape as PR-030's transformer fixture: patch ``get_secrets`` on the source module,
    evict any previously-imported copy (it would carry real module-level bucket names), then
    import.
    """
    import loteria.common.aws_secrets as aws_secrets

    monkeypatch.setattr(
        aws_secrets,
        "get_secrets",
        lambda: {"partitioned": PARTITIONED, "simple": SIMPLE, "scrape_do_token": TOKEN},
    )
    sys.modules.pop("loteria.extractor.scraping", None)
    sys.modules.pop("loteria.extractor.lambda_handler", None)

    module = importlib.import_module("loteria.extractor.scraping")

    # Silence the real metric publish; the metrics module is covered on its own.
    monkeypatch.setattr(module, "record_scraper_status", lambda status: None)

    yield module

    sys.modules.pop("loteria.extractor.scraping", None)
    sys.modules.pop("loteria.extractor.lambda_handler", None)


@pytest.fixture
def pages(monkeypatch, scraping):
    """Serve canned pages for the two requests the extractor makes."""

    def _install(award=AWARD_PAGE, detail=DETAIL_PAGE, status=200):
        requested = []

        def fake_get(url, **kwargs):
            requested.append(url)
            body = award if len(requested) == 1 else detail
            return FakeResponse(body, status)

        monkeypatch.setattr(scraping.requests, "get", fake_get)
        return requested

    return _install


# ==========================================================================================
# fetch_via_proxy
# ==========================================================================================
class TestFetchViaProxy:
    def test_builds_a_scrape_do_url_with_the_target_encoded(self, scraping, monkeypatch):
        """The target goes in a query parameter, so an unencoded `?` or `&` in it would
        silently truncate the URL the proxy is asked to fetch."""
        seen = {}

        def fake_get(url, **kwargs):
            seen["url"] = url
            return FakeResponse("ok")

        monkeypatch.setattr(scraping.requests, "get", fake_get)
        scraping.fetch_via_proxy("https://loteria.org.gt/site/award?x=1&y=2")

        assert "url=https%3A%2F%2Floteria.org.gt%2Fsite%2Faward%3Fx%3D1%26y%3D2" in seen["url"]
        assert f"token={TOKEN}" in seen["url"]

    def test_sends_a_timeout(self, scraping, monkeypatch):
        """Without one, a hung proxy would sit until the Lambda's own timeout and produce a
        far less legible failure."""
        seen = {}

        def fake_get(url, **kwargs):
            seen.update(kwargs)
            return FakeResponse("ok")

        monkeypatch.setattr(scraping.requests, "get", fake_get)
        scraping.fetch_via_proxy("https://example.com")

        assert seen["timeout"] > 0

    @pytest.mark.parametrize("status", [401, 402, 429, 500])
    def test_a_non_200_raises(self, scraping, monkeypatch, status):
        monkeypatch.setattr(
            scraping.requests, "get", lambda url, **kw: FakeResponse("nope", status)
        )

        with pytest.raises(ValueError, match=str(status)):
            scraping.fetch_via_proxy("https://example.com")

    def test_the_status_is_recorded_before_the_raise(self, scraping, monkeypatch):
        """PR-026's whole point. A metric emitted after the raise would only ever record
        successes — the 401/402/429 responses it exists to catch are precisely the ones that
        never reach a line placed below it."""
        recorded = []
        monkeypatch.setattr(scraping, "record_scraper_status", recorded.append)
        monkeypatch.setattr(scraping.requests, "get", lambda url, **kw: FakeResponse("nope", 402))

        with pytest.raises(ValueError):
            scraping.fetch_via_proxy("https://example.com")

        assert recorded == [402]


# ==========================================================================================
# extract_lottery_data
# ==========================================================================================
class TestExtractLotteryData:
    def test_writes_a_file_and_returns_its_path(self, s3, scraping, pages, tmp_path):
        pages()
        path = scraping.extract_lottery_data(output_folder=str(tmp_path))

        assert path is not None
        assert (tmp_path / path.split("/")[-1]).exists()

    def test_the_file_has_the_header_body_structure_the_parser_expects(
        self, s3, scraping, pages, tmp_path
    ):
        """``split_header_body`` looks for the literal lines HEADER and BODY. This is the
        contract between the two halves of the pipeline, and nothing else checks it."""
        pages()
        path = scraping.extract_lottery_data(output_folder=str(tmp_path))
        content = open(path, encoding="utf-8").read()

        assert content.startswith("HEADER\n")
        assert "\nBODY\n" in content
        assert content.index("HEADER") < content.index("BODY")

    def test_uploads_to_both_buckets(self, s3, scraping, pages, tmp_path):
        pages()
        scraping.extract_lottery_data(output_folder=str(tmp_path))

        partitioned = s3.list_objects_v2(Bucket=PARTITIONED).get("Contents", [])
        simple = s3.list_objects_v2(Bucket=SIMPLE).get("Contents", [])

        assert len(partitioned) == 1
        assert len(simple) == 1

    def test_the_partitioned_key_is_hive_partitioned_by_year_and_sorteo(
        self, s3, scraping, pages, tmp_path
    ):
        """The crawlers and every Athena query depend on this layout. The year comes from
        FECHA DEL SORTEO, and the sorteo number from the h2 — not from the URL id."""
        pages()
        scraping.extract_lottery_data(output_folder=str(tmp_path))

        key = s3.list_objects_v2(Bucket=PARTITIONED)["Contents"][0]["Key"]
        assert key.startswith("raw/year=2024/sorteo=3046/")

    def test_the_sorteo_number_comes_from_the_heading_not_the_url_id(
        self, s3, scraping, pages, tmp_path
    ):
        """The award page links carry `id=999`, an internal identifier that is NOT the draw
        number. Filing under the URL id would scatter draws across nonsense partitions."""
        pages()
        scraping.extract_lottery_data(output_folder=str(tmp_path))

        key = s3.list_objects_v2(Bucket=PARTITIONED)["Contents"][0]["Key"]
        assert "sorteo=3046" in key
        assert "sorteo=999" not in key

    def test_the_simple_key_is_flat(self, s3, scraping, pages, tmp_path):
        pages()
        scraping.extract_lottery_data(output_folder=str(tmp_path))

        assert s3.list_objects_v2(Bucket=SIMPLE)["Contents"][0]["Key"] == "raw/sorteo_3046.txt"

    def test_an_already_processed_sorteo_is_skipped(self, s3, scraping, pages, tmp_path):
        """Idempotency: the weekly cron may run twice, or a manual retry may follow a
        successful run. Re-uploading would be harmless, but returning None is what tells the
        caller nothing new arrived."""
        s3.put_object(
            Bucket=PARTITIONED,
            Key="processed/year=2024/sorteo=3046/sorteos.parquet",
            Body=b"x",
        )
        pages()

        assert scraping.extract_lottery_data(output_folder=str(tmp_path)) is None

    def test_nothing_is_uploaded_when_the_sorteo_is_skipped(self, s3, scraping, pages, tmp_path):
        s3.put_object(
            Bucket=PARTITIONED,
            Key="processed/year=2024/sorteo=3046/sorteos.parquet",
            Body=b"x",
        )
        pages()
        scraping.extract_lottery_data(output_folder=str(tmp_path))

        assert s3.list_objects_v2(Bucket=SIMPLE).get("Contents", []) == []

    def test_a_specific_lottery_number_selects_its_link(self, s3, scraping, monkeypatch, tmp_path):
        """The backfill path. Without the `id=` filter it would silently scrape the latest
        draw instead of the one asked for."""
        requested = []

        def fake_get(url, **kwargs):
            requested.append(url)
            return FakeResponse(AWARD_PAGE if len(requested) == 1 else DETAIL_PAGE)

        monkeypatch.setattr(scraping.requests, "get", fake_get)
        scraping.extract_lottery_data(lottery_number=998, output_folder=str(tmp_path))

        assert "id%3D998" in requested[1]

    def test_a_centenares_marker_is_added_when_the_body_does_not_start_with_00mil(
        self, s3, scraping, pages, tmp_path
    ):
        """The parser's body regex needs the section header. A page whose results start
        directly with a prize line would otherwise lose its first block."""
        detail = DETAIL_PAGE.replace("00MIL\n", "")
        pages(detail=detail)

        path = scraping.extract_lottery_data(output_folder=str(tmp_path))
        assert "CENTENARES" in open(path, encoding="utf-8").read()

    def test_no_centenares_marker_when_the_body_already_starts_with_00mil(
        self, s3, scraping, pages, tmp_path
    ):
        pages()
        path = scraping.extract_lottery_data(output_folder=str(tmp_path))

        assert "CENTENARES" not in open(path, encoding="utf-8").read()


class TestExtractorFailureModes:
    """Each of these is a distinct way loteria.org.gt can change under the pipeline. They
    matter because the messages are what someone reads in CloudWatch at the point where the
    weekly run has already failed."""

    def test_a_page_with_no_sorteo_link_raises(self, s3, scraping, pages, tmp_path):
        """The Cloudflare waiting-room signature: HTTP 200, real HTML, no draw links."""
        pages(award="<html><body><div class='container'>queue</div></body></html>")

        with pytest.raises(ValueError, match="enlace al sorteo"):
            scraping.extract_lottery_data(output_folder=str(tmp_path))

    def test_a_link_without_an_id_parameter_raises(self, s3, scraping, pages, tmp_path):
        award = "<html><body><div class='container'><a href='/x?id='>x</a></div></body></html>"
        pages(award=award)

        with pytest.raises(ValueError, match="ID del sorteo"):
            scraping.extract_lottery_data(output_folder=str(tmp_path))

    def test_a_heading_without_a_draw_number_raises(self, s3, scraping, pages, tmp_path):
        detail = DETAIL_PAGE.replace("SORTEO   ORDINARIO NO. 3046", "BIENVENIDOS")
        pages(detail=detail)

        with pytest.raises(ValueError, match="número del sorteo"):
            scraping.extract_lottery_data(output_folder=str(tmp_path))

    def test_too_few_result_rows_raises(self, s3, scraping, pages, tmp_path):
        """The extractor indexes ``result_divs[2]`` positionally. Fewer than three rows means
        the layout moved, and reading index 2 anyway would write the wrong text to raw/."""
        detail = DETAIL_PAGE.replace('<div class="row">filters</div>', "")
        pages(detail=detail)

        with pytest.raises(ValueError, match="sección de resultados"):
            scraping.extract_lottery_data(output_folder=str(tmp_path))

    def test_an_absolute_href_is_used_as_is(self, s3, scraping, pages, tmp_path):
        """Relative hrefs get the domain prepended; an absolute one must not be doubled up."""
        award = AWARD_PAGE.replace(
            'href="/site/awardDetail?id=999"', 'href="https://x.gt/a?id=999"'
        )
        requested = pages(award=award)

        scraping.extract_lottery_data(output_folder=str(tmp_path))
        assert "https%3A%2F%2Fx.gt%2Fa%3Fid%3D999" in requested[1]


class TestYearDerivation:
    """The year is the Hive partition. Getting it wrong misfiles the draw somewhere the
    crawler will still happily register, so nothing downstream complains."""

    def test_the_year_comes_from_the_draw_date(self, s3, scraping, pages, tmp_path):
        detail = DETAIL_PAGE.replace("FECHA DEL SORTEO: 01/06/2024", "FECHA DEL SORTEO: 09/08/2026")
        pages(detail=detail)

        scraping.extract_lottery_data(output_folder=str(tmp_path))
        key = s3.list_objects_v2(Bucket=PARTITIONED)["Contents"][0]["Key"]

        assert "year=2026" in key

    def test_a_missing_date_falls_back_to_unknown(self, s3, scraping, pages, tmp_path):
        """Deliberately not a raise: the prizes are still worth capturing, and a partition
        literally named `year=unknown` is a visible, greppable signal rather than a silent
        misfile into a plausible-looking year."""
        detail = DETAIL_PAGE.replace("FECHA DEL SORTEO: 01/06/2024", "")
        pages(detail=detail)

        scraping.extract_lottery_data(output_folder=str(tmp_path))
        key = s3.list_objects_v2(Bucket=PARTITIONED)["Contents"][0]["Key"]

        assert "year=unknown" in key

    def test_a_partially_numeric_date_yields_a_truncated_year_DEFECT(
        self, s3, scraping, pages, tmp_path
    ):
        """⚠️ DOCUMENTS A DEFECT, found by writing this test. Not the desired behaviour.

        The date regex is ``FECHA DEL SORTEO:\\s*([\\d/]+)`` — an unanchored character class,
        so on ``01/06/20XX`` it matches the prefix ``01/06/20`` rather than failing. The year
        then parses cleanly as ``20`` and the draw is filed under ``raw/year=20/``. The
        ``except (ValueError, IndexError)`` fallback to ``"unknown"`` never fires, because
        nothing raised.

        A partition named ``year=unknown`` is greppable; ``year=20`` looks like real data and
        the crawler registers it without complaint.

        NOT fixed here on purpose: PR-035 is a coverage ratchet, and changing the extractor's
        parsing would alter what the weekly production run does for a case the site has never
        actually produced (all 111 real captures are ``dd/mm/yyyy``). The fix is to anchor the
        pattern to ``\\d{2}/\\d{2}/\\d{4}``. Recorded as a follow-up in roadmap.md.
        """
        detail = DETAIL_PAGE.replace("01/06/2024", "01/06/20XX")
        pages(detail=detail)

        scraping.extract_lottery_data(output_folder=str(tmp_path))
        key = s3.list_objects_v2(Bucket=PARTITIONED)["Contents"][0]["Key"]

        assert "year=20/" in key, "if this now says year=unknown, the defect was fixed"


class TestHeaderNormalisation:
    def test_blank_lines_and_runs_of_spaces_are_collapsed(self, s3, scraping, pages, tmp_path):
        """``process_header`` joins the header with a single space before matching its
        regexes, so a header carrying the page's original blank lines would not match."""
        pages()
        path = scraping.extract_lottery_data(output_folder=str(tmp_path))
        header = open(path, encoding="utf-8").read().split("BODY")[0]

        assert "\n\n\n" not in header
        assert "FECHA DEL SORTEO: 01/06/2024" in header

    def test_a_missing_header_div_leaves_the_header_empty_rather_than_crashing(
        self, s3, scraping, pages, tmp_path
    ):
        """The h2 still carries the draw number, so extraction can continue; the transformer
        is where an unparseable header becomes a loud failure."""
        detail = DETAIL_PAGE.replace('class="heading_s1 text-center"', 'class="something-else"')
        pages(detail=detail)

        path = scraping.extract_lottery_data(output_folder=str(tmp_path))
        assert path is not None


# ==========================================================================================
# lambda_handler
# ==========================================================================================
class TestLambdaHandler:
    @pytest.fixture
    def handler(self, scraping, monkeypatch):
        module = importlib.import_module("loteria.extractor.lambda_handler")
        monkeypatch.setattr(module, "extract_lottery_data", lambda n: f"/tmp/sorteo_{n}.txt")
        return module

    def test_returns_ok_and_the_written_path(self, handler):
        assert handler.lambda_handler({}, None) == {"status": "ok", "file": "/tmp/sorteo_None.txt"}

    def test_a_none_event_is_tolerated(self, handler):
        """A manual `aws lambda invoke` with no payload delivers None, not {}."""
        assert handler.lambda_handler(None, None)["status"] == "ok"

    def test_the_lottery_number_is_forwarded(self, handler):
        assert handler.lambda_handler({"lottery_number": 3046}, None)["file"].endswith("3046.txt")

    def test_correlation_id_is_promoted_to_the_environment(self, handler, monkeypatch):
        """PR-018: it has to land in os.environ BEFORE configure_logging reads it, or the
        Lambda's log lines get a fresh uuid and cannot be joined to the Glue job's."""
        monkeypatch.delenv("CORRELATION_ID", raising=False)
        handler.lambda_handler({"CORRELATION_ID": "exec-7"}, None)

        import os

        assert os.environ["CORRELATION_ID"] == "exec-7"

    def test_a_scrape_failure_propagates(self, handler, monkeypatch):
        """The Step Function's error handling depends on the invoke failing. Swallowing here
        would let the transformer run against a raw/ prefix nothing was added to."""

        def boom(_n):
            raise ValueError("❌ No se pudo encontrar el enlace al sorteo.")

        monkeypatch.setattr(handler, "extract_lottery_data", boom)

        with pytest.raises(ValueError):
            handler.lambda_handler({}, None)
