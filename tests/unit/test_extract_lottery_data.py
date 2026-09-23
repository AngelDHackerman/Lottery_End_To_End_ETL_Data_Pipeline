"""What the extractor DOES with a page once it has one (PR-035).

``tests/unit/test_scraping.py`` covers the two things PR-031.1 rewrote — the scrape.do proxy
profile and the prize-list locator — against a real captured page. This file covers the other
half of the module: ``extract_lottery_data``, the orchestration around them. Which branch it
takes, what it writes, and where it uploads it. Those are the parts a live canary cannot
check without polluting prod.

It is a separate file rather than more classes in ``test_scraping.py`` for one mechanical
reason: ``scraping.py`` calls ``get_secrets()`` at **import** time, so both files import it
under a patch, and they need different fakes (this one needs bucket names that exist in
moto). Two fixtures popping the same entry out of ``sys.modules`` in one file is a trap for
whoever adds the next test.

The HTML here is minimal by design. It is not a copy of loteria.org.gt — pinning the real
selectors is the canary's job, weekly, against the real site. What this pins is behaviour.

Rescued from `origin/feat/PR-035-coverage-85`, which was written in August 2026 and never
merged (the stacked-PR chain collapsed; see roadmap PR-035). The tests are mostly as they
were; the page fixture was rebuilt for the post-redesign markup, since the container these
tests used to rely on is the one PR-031.1 found full of legal boilerplate.
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


def _prize_items(first: str = "00MIL") -> str:
    """Twelve prize-shaped rows, over ``MIN_PRIZE_LINES`` on purpose.

    The threshold is what tells a real prize list apart from a container that merely exists,
    so a fixture sitting exactly on it would make every test here a boundary test by
    accident. The leading section label matters separately: the parser needs it, and
    ``extract_lottery_data`` inserts CENTENARES only when the body does not already open
    with one.
    """
    rows = [f'<div class="premio-item">{first}</div>'] if first else []
    rows += [
        f'<div class="premio-item">{1000 + i:05d}   P   ....   {700 + i}.00</div>'
        for i in range(12)
    ]
    return "\n".join(rows)


def _detail_page(prizes: str | None = None) -> str:
    return f"""
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
    <div class="row">el buscador de billetes</div>
    <div class="row"><div id="div_resultado"></div></div>
    <div class="row">7,920 reintegros de Q100.00 c/u. ESTIMADO PUBLICO…</div>
  </div>
  <div class="lista-premios-columnas">
    {_prize_items() if prizes is None else prizes}
  </div>
</body></html>
"""


DETAIL_PAGE = _detail_page()


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
    evict any previously-imported copy (it would carry another test module's bucket names),
    then import.
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

    # Silence the real metric publish; metrics.py is covered on its own.
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
        """Fault A in one line: every capture is written twice, and this is the copy nothing
        reads. Still true by default — PR-041.1 gates this write, it does not remove it."""
        pages()
        scraping.extract_lottery_data(output_folder=str(tmp_path))

        assert s3.list_objects_v2(Bucket=SIMPLE)["Contents"][0]["Key"] == "raw/sorteo_3046.txt"


class TestSimpleBucketWritesFlag:
    """PR-041.1 — the write the roadmap's own PR-041 prompt forgets.

    That prompt lists the transformer's two Parquet copies and stops there. The extractor
    writes the raw .txt to the simple bucket as well, and a flag that stopped only two of
    the three writes would leave the bucket growing every Thursday while the PR claimed it
    had stopped — which is worse than not having touched it, because the next person would
    trust the claim.

    Delivered as an environment variable here, not a job argument: this one runs in Lambda.
    ``loteria.common.config`` is what keeps the two spellings meaning the same thing.
    """

    def test_the_raw_copy_stops(self, s3, scraping, pages, tmp_path, monkeypatch):
        monkeypatch.setenv("ENABLE_SIMPLE_BUCKET_WRITES", "false")
        pages()

        scraping.extract_lottery_data(output_folder=str(tmp_path))

        assert s3.list_objects_v2(Bucket=SIMPLE).get("Contents", []) == []

    def test_the_partitioned_copy_is_untouched(self, s3, scraping, pages, tmp_path, monkeypatch):
        """The Hive-style key is the transformer's only input. If disabling the duplicate
        touched it, the flag would break the pipeline rather than trim it."""
        monkeypatch.setenv("ENABLE_SIMPLE_BUCKET_WRITES", "false")
        pages()

        scraping.extract_lottery_data(output_folder=str(tmp_path))

        key = s3.list_objects_v2(Bucket=PARTITIONED)["Contents"][0]["Key"]
        assert key.startswith("raw/year=2024/sorteo=3046/")

    def test_writing_is_the_default(self, s3, scraping, pages, tmp_path, monkeypatch):
        monkeypatch.delenv("ENABLE_SIMPLE_BUCKET_WRITES", raising=False)
        pages()

        scraping.extract_lottery_data(output_folder=str(tmp_path))

        assert len(s3.list_objects_v2(Bucket=SIMPLE).get("Contents", [])) == 1

    def test_the_flag_is_read_per_invocation_not_at_import(
        self, s3, scraping, pages, tmp_path, monkeypatch
    ):
        """scraping.py already does real work at import (`get_secrets()`), and PR-017 had to
        unpick one value being read there. Reading this one at call time means flipping it
        in Terraform takes effect on the next invocation — no rebuild of the zip, no
        redeploy — which is the only reason it is worth having as a flag at all."""
        pages()
        monkeypatch.setenv("ENABLE_SIMPLE_BUCKET_WRITES", "true")
        scraping.extract_lottery_data(output_folder=str(tmp_path))

        monkeypatch.setenv("ENABLE_SIMPLE_BUCKET_WRITES", "false")
        s3.delete_object(Bucket=PARTITIONED, Key="processed/year=2024/sorteo=3046/sorteos.parquet")
        pages()
        scraping.extract_lottery_data(lottery_number=998, output_folder=str(tmp_path))

        # One object: the first call's, from before the flip. The second call wrote none.
        assert len(s3.list_objects_v2(Bucket=SIMPLE)["Contents"]) == 1

    def test_the_body_carries_the_prize_lines(self, s3, scraping, pages, tmp_path):
        """The failure PR-031.1 was built to make impossible: a raw file with a header, a
        BODY marker, and no prizes under it. Structure alone is not evidence of content."""
        pages()
        path = scraping.extract_lottery_data(output_folder=str(tmp_path))
        body = open(path, encoding="utf-8").read().split("\nBODY\n", 1)[1]

        assert "01000 P .... 700.00" in body
        assert body.count(" P .... ") == 12

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
        pages(detail=_detail_page(prizes=_prize_items(first="")))

        path = scraping.extract_lottery_data(output_folder=str(tmp_path))
        assert "CENTENARES" in open(path, encoding="utf-8").read()

    def test_no_centenares_marker_when_the_body_already_starts_with_00mil(
        self, s3, scraping, pages, tmp_path
    ):
        pages()
        path = scraping.extract_lottery_data(output_folder=str(tmp_path))

        assert "CENTENARES" not in open(path, encoding="utf-8").read()


class TestTheIdempotencyGuard:
    """PR-035.1 A. Until this PR the guard asked for ``processed/year=<Y>/sorteo=<N>/``, a
    prefix nothing had written since 2025-11-24, so it never fired. It now looks where the
    transformer actually writes a finished draw: ``silver/sorteos/``.

    It runs after both proxied fetches, so a skip saves no scrape.do credits. What it saves
    is the raw/ rewrite (a new object version on a versioned bucket) and the simple copy.
    """

    SILVER_KEY = "silver/sorteos/year=2024/sorteo=3046/sorteos.parquet"

    def test_a_draw_already_in_silver_is_skipped(self, s3, scraping, pages, tmp_path):
        s3.put_object(Bucket=PARTITIONED, Key=self.SILVER_KEY, Body=b"x")
        pages()

        assert scraping.extract_lottery_data(output_folder=str(tmp_path)) is None

    def test_nothing_is_uploaded_when_the_draw_is_skipped(self, s3, scraping, pages, tmp_path):
        s3.put_object(Bucket=PARTITIONED, Key=self.SILVER_KEY, Body=b"x")
        pages()
        scraping.extract_lottery_data(output_folder=str(tmp_path))

        assert [o["Key"] for o in s3.list_objects_v2(Bucket=PARTITIONED)["Contents"]] == [
            self.SILVER_KEY
        ]
        assert s3.list_objects_v2(Bucket=SIMPLE).get("Contents", []) == []

    def test_raw_alone_does_not_skip(self, s3, scraping, pages, tmp_path):
        """A draw that was scraped but never transformed (the transform failed) must be
        scraped again: raw/ is not proof the draw made it into the lake."""
        s3.put_object(Bucket=PARTITIONED, Key="raw/year=2024/sorteo=3046/results.txt", Body=b"x")
        pages()

        assert scraping.extract_lottery_data(output_folder=str(tmp_path)) is not None

    def test_the_legacy_processed_prefix_no_longer_skips(self, s3, scraping, pages, tmp_path):
        s3.put_object(
            Bucket=PARTITIONED,
            Key="processed/year=2024/sorteo=3046/sorteos.parquet",
            Body=b"x",
        )
        pages()

        assert scraping.extract_lottery_data(output_folder=str(tmp_path)) is not None


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

    def test_a_missing_prize_container_raises_instead_of_writing_a_prizeless_file(
        self, s3, scraping, pages, tmp_path
    ):
        """``extract_prize_body`` is tested on its own in test_scraping.py; what is asserted
        here is that ``extract_lottery_data`` lets it through rather than writing the file
        anyway. Nothing is uploaded, which is the outcome that matters."""
        detail = DETAIL_PAGE.replace("lista-premios-columnas", "lista-premios-vieja")
        pages(detail=detail)

        with pytest.raises(ValueError, match="sección de resultados"):
            scraping.extract_lottery_data(output_folder=str(tmp_path))

        assert s3.list_objects_v2(Bucket=PARTITIONED).get("Contents", []) == []

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

    @pytest.mark.parametrize(
        "fecha",
        ["01/06/20XX", "1/6/2024", "01/06/24", "01/06/20245"],
        ids=["truncated-year", "unpadded", "two-digit-year", "five-digit-year"],
    )
    def test_anything_short_of_a_full_date_falls_back_to_unknown(
        self, s3, scraping, pages, tmp_path, fecha
    ):
        """PR-035.1 B. The old pattern ``([\\d/]+)`` took whatever run of digits and slashes
        it found, so ``01/06/20XX`` filed the draw under ``raw/year=20/`` — a real-looking
        partition the crawler registers without complaint. Anchored to dd/mm/yyyy, every
        malformed date lands in the greppable ``year=unknown`` instead."""
        detail = DETAIL_PAGE.replace("01/06/2024", fecha)
        pages(detail=detail)

        scraping.extract_lottery_data(output_folder=str(tmp_path))
        key = s3.list_objects_v2(Bucket=PARTITIONED)["Contents"][0]["Key"]

        assert "year=unknown/" in key


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
