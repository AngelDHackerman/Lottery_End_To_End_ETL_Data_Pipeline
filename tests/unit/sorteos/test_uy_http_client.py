"""The polite client: privacy blocklist, retries, redirects, rate limit (UY-001)."""

from __future__ import annotations

import pytest
import requests
from requests.structures import CaseInsensitiveDict

from sorteos.core import http_client
from sorteos.core.http_client import (
    BlockedURLError,
    FetchError,
    PoliteClient,
    _RateLimiter,
)
from sorteos.uy import privacy
from sorteos.uy.privacy import blocked_pattern

# The three files the brief lists as EXCLUDED. Strings only: nothing here may fetch them.
EXCLUDED = [
    "https://www.loteria.gub.uy/invalidas/20160706/TDI_06072016_DET_INVALIDAS_GENERAL_TELEFONICAS.PDF",
    "https://www.loteria.gub.uy/invalidas/20160706/QDI_06072016_DET_INVALIDAS_GENERAL_TELEFONICAS.PDF",
    "https://www.loteria.gub.uy/invalidas/06072016/ORO_06072016_DET_INVALIDAS_GENERAL_TELEFONICAS.PDF",
]
POZOS = "https://www.loteria.gub.uy/invalidas/06072016/ORO_06072016_RES_INFORMACION_DE_POZOS.PDF"
AGENT = "test-agent/1.0"


def response(status=200, content=b"ok", headers=None) -> requests.Response:
    r = requests.Response()
    r.status_code = status
    r._content = content
    r.headers = CaseInsensitiveDict(headers or {})
    return r


class FakeSession:
    """Answers from a queue per URL and records every request it was asked to make."""

    def __init__(self, answers: dict):
        self.answers = {url: list(items) for url, items in answers.items()}
        self.calls: list[str] = []
        self.headers: dict = {}

        self.posted: list[tuple[str, dict]] = []  # (url, form) of every POST

    def get(self, url, timeout, allow_redirects):
        assert allow_redirects is False, "redirects must be followed by hand"
        self.calls.append(url)
        item = self.answers[url].pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def post(self, url, data, timeout, allow_redirects):
        self.posted.append((url, data))
        return self.get(url, timeout, allow_redirects)


def client(session, **kwargs) -> PoliteClient:
    kwargs.setdefault("sleep", lambda _s: None)
    return privacy.polite_client(session=session, **kwargs)


@pytest.mark.parametrize("url", EXCLUDED)
def test_the_brief_exclusions_are_blocked(url):
    assert blocked_pattern(url) == "DET_INVALIDAS"


@pytest.mark.parametrize(
    "url",
    [
        EXCLUDED[0].lower(),
        EXCLUDED[0].replace("DET_INVALIDAS", "DET%5FINVALIDAS"),
        EXCLUDED[0].replace("DET_INVALIDAS", "DET%255FINVALIDAS"),
        "https://example.org/?next=" + EXCLUDED[1],
    ],
)
def test_case_and_encoding_do_not_hide_the_pattern(url):
    assert blocked_pattern(url) == "DET_INVALIDAS"


def test_the_pozos_pdf_is_allowed():
    assert blocked_pattern(POZOS) is None


@pytest.mark.parametrize("url", EXCLUDED)
def test_blocked_url_never_reaches_the_network(url, caplog):
    session = FakeSession({})
    with pytest.raises(BlockedURLError) as exc:
        client(session).get(url)
    assert session.calls == []
    # The pattern is reported; the file's URL is not.
    assert url not in str(exc.value)
    assert url not in caplog.text


def test_a_redirect_into_a_blocked_file_is_refused_before_the_second_hop():
    start = "https://www.loteria.gub.uy/x.php"
    session = FakeSession({start: [response(302, b"", {"Location": EXCLUDED[2]})]})
    with pytest.raises(BlockedURLError):
        client(session).get(start)
    assert session.calls == [start]


def test_redirects_are_followed_and_reported():
    start = "https://www.loteria.gub.uy/a"
    session = FakeSession(
        {
            start: [response(301, b"", {"Location": "/b"})],
            "https://www.loteria.gub.uy/b": [response(200, b"page")],
        }
    )
    result = client(session).get(start)
    assert result.url == start
    assert result.final_url == "https://www.loteria.gub.uy/b"
    assert result.content == b"page"


def test_a_3xx_without_location_is_returned_as_is():
    url = "https://www.loteria.gub.uy/a"
    result = client(FakeSession({url: [response(304, b"")]})).get(url)
    assert result.status == 304


def test_too_many_redirects_gives_up(monkeypatch):
    url = "https://www.loteria.gub.uy/loop"
    loop = [response(302, b"", {"Location": url}) for _ in range(20)]
    with pytest.raises(FetchError):
        client(FakeSession({url: loop}), max_retries=0).get(url)


def test_user_agent_names_a_contact_and_can_be_overridden(monkeypatch):
    monkeypatch.delenv("LOTERIA_UY_CONTACT", raising=False)
    s = FakeSession({})
    assert http_client.DEFAULT_CONTACT in client(s).user_agent
    assert s.headers["User-Agent"] == client(s).user_agent
    monkeypatch.setenv("LOTERIA_UY_CONTACT", "https://example.org/contact")
    assert "https://example.org/contact" in client(FakeSession({})).user_agent


def test_5xx_is_retried_with_backoff_and_retry_after_is_honoured():
    url = "https://www.loteria.gub.uy/a"
    sleeps: list[float] = []
    session = FakeSession(
        {url: [response(503, headers={"Retry-After": "40"}), response(429), response(200, b"x")]}
    )
    result = client(session, sleep=sleeps.append).get(url)
    assert result.status == 200
    assert len(session.calls) == 3
    # sleeps mixes the 1 s rate-limit waits with the backoffs; the first backoff honours
    # Retry-After over the shorter computed delay.
    backoffs = [s for s in sleeps if s > 1.0]
    assert backoffs[0] >= 40


def test_retries_are_bounded_for_statuses():
    url = "https://www.loteria.gub.uy/a"
    session = FakeSession({url: [response(502) for _ in range(3)]})
    with pytest.raises(FetchError, match="HTTP 502 after 3 attempts"):
        client(session, max_retries=2).get(url)


def test_retries_are_bounded_for_transport_errors():
    url = "https://www.loteria.gub.uy/a"
    boom = requests.ConnectionError("reset")
    session = FakeSession({url: [boom, response(200, b"x")]})
    assert client(session, max_retries=1).get(url).status == 200
    session = FakeSession({url: [boom, boom]})
    with pytest.raises(FetchError, match="ConnectionError after 2 attempts"):
        client(session, max_retries=1).get(url)


def test_a_404_is_returned_not_retried():
    url = "https://www.loteria.gub.uy/x.pdf"
    session = FakeSession({url: [response(404)]})
    assert client(session).get(url).status == 404
    assert len(session.calls) == 1


def test_faster_than_one_request_per_second_is_refused():
    with pytest.raises(ValueError):
        privacy.polite_client(min_interval=0.5, session=FakeSession({}))


def test_rate_limiter_spaces_request_starts():
    now = [100.0]
    slept: list[float] = []

    def sleep(seconds):
        slept.append(seconds)
        now[0] += seconds

    limiter = _RateLimiter()
    limiter.wait(1.0, clock=lambda: now[0], sleep=sleep)
    now[0] += 0.25
    limiter.wait(1.0, clock=lambda: now[0], sleep=sleep)
    assert slept == [pytest.approx(0.75)]


# --- The blocklist is the caller's, and it has no default (UY-020; DESIGN.md, P5) ---------


def test_a_client_cannot_be_built_without_a_blocklist():
    with pytest.raises(TypeError, match="blocklist"):
        PoliteClient(agent=AGENT, session=FakeSession({}))


def test_a_single_string_is_refused_not_iterated_letter_by_letter():
    with pytest.raises(TypeError, match="not a single string"):
        PoliteClient(blocklist="DET_INVALIDAS", agent=AGENT, session=FakeSession({}))


@pytest.mark.parametrize("bad", ["", "   ", None, 7])
def test_an_empty_or_non_text_pattern_is_refused(bad):
    # An empty pattern would match every URL; anything not a string is a mistake.
    with pytest.raises(ValueError, match="non-empty strings"):
        PoliteClient(blocklist=("DET_INVALIDAS", bad), agent=AGENT, session=FakeSession({}))


def test_an_empty_blocklist_is_allowed_when_said_out_loud():
    url = "https://example.test/DET_INVALIDAS.pdf"
    session = FakeSession({url: [response(200)]})
    no_guard = PoliteClient(blocklist=(), agent=AGENT, session=session, sleep=lambda _s: None)
    assert no_guard.get(url).status == 200


def test_patterns_are_matched_whatever_case_they_were_given_in():
    session = FakeSession({})
    lower = PoliteClient(
        blocklist=("det_invalidas",), agent=AGENT, session=session, sleep=lambda _s: None
    )
    assert lower.blocklist == ("DET_INVALIDAS",)
    with pytest.raises(BlockedURLError):
        lower.get(EXCLUDED[0])
    assert session.calls == []


def test_the_uruguayan_client_always_carries_the_uruguayan_blocklist():
    assert privacy.polite_client(session=FakeSession({})).blocklist == ("DET_INVALIDAS",)
    # And it cannot be swapped for another one on the way in.
    with pytest.raises(TypeError):
        privacy.polite_client(blocklist=(), session=FakeSession({}))


def test_the_core_guard_knows_no_country():
    # The pattern lives in sorteos.uy.privacy only; core would match nothing on its own.
    assert not hasattr(http_client, "BLOCKED_PATTERNS")
    assert http_client.blocked_pattern(EXCLUDED[0], ()) is None


# --- The agent is the caller's too (UY-020) ----------------------------------------------


def test_the_uruguayan_user_agent_is_byte_for_byte_the_one_the_dnlq_has_always_seen(
    monkeypatch,
):
    # Moving the agent out of core must not change what reaches the site's access logs.
    monkeypatch.delenv("LOTERIA_UY_CONTACT", raising=False)
    assert privacy.polite_client(session=FakeSession({})).user_agent == (
        "loteria-uy-research/0.1 (data-engineering portfolio; "
        "+https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline)"
    )


def test_a_client_cannot_be_built_without_an_agent():
    with pytest.raises(TypeError, match="agent"):
        PoliteClient(blocklist=(), session=FakeSession({}))


@pytest.mark.parametrize("bad", ["", "loteria-uy-research", "a b/1", "x/1 (y)", None])
def test_the_agent_must_be_a_product_version_token(bad):
    with pytest.raises(ValueError, match="product/version"):
        PoliteClient(blocklist=(), agent=bad, session=FakeSession({}))


def test_the_uruguayan_agent_cannot_be_swapped_on_the_way_in():
    with pytest.raises(TypeError):
        privacy.polite_client(agent="other/1.0", session=FakeSession({}))


# --- POST (UY-030.2: the ver_estadisticas form) -------------------------------------------

FORM_URL = "https://www.loteria.gub.uy/ver_estadisticas.php?xjue=4&xpos=1"
FORM = {"xdia": "1", "xmes": "01", "xano": "2006"}


def test_a_post_sends_its_form_and_returns_the_page():
    session = FakeSession({FORM_URL: [response(200, b"counts")]})
    result = client(session).post(FORM_URL, FORM)
    assert (result.status, result.content, result.url) == (200, b"counts", FORM_URL)
    assert session.posted == [(FORM_URL, FORM)]


def test_a_post_is_retried_like_a_get_with_the_same_form():
    session = FakeSession({FORM_URL: [response(503), response(200, b"counts")]})
    assert client(session).post(FORM_URL, FORM).content == b"counts"
    assert session.posted == [(FORM_URL, FORM), (FORM_URL, FORM)]


def test_a_blocked_url_is_never_posted_to():
    session = FakeSession({})
    with pytest.raises(BlockedURLError):
        client(session).post(EXCLUDED[0], FORM)
    assert session.posted == []


@pytest.mark.parametrize(("status", "posts"), [(303, 1), (302, 1), (307, 2), (308, 2)])
def test_after_a_redirect_a_post_goes_on_as_get_unless_307_or_308(status, posts):
    after = "https://www.loteria.gub.uy/resultado.php"
    session = FakeSession(
        {
            FORM_URL: [response(status, b"", {"Location": "/resultado.php"})],
            after: [response(200, b"counts")],
        }
    )
    result = client(session).post(FORM_URL, FORM)
    assert result.final_url == after
    assert [url for url, _ in session.posted] == [FORM_URL, after][:posts]
    assert session.calls == [FORM_URL, after]


def test_a_post_redirected_into_a_blocked_file_is_refused():
    session = FakeSession({FORM_URL: [response(303, b"", {"Location": EXCLUDED[1]})]})
    with pytest.raises(BlockedURLError):
        client(session).post(FORM_URL, FORM)
    assert session.calls == [FORM_URL]


def test_the_form_is_copied_so_a_caller_cannot_change_it_between_retries():
    form = dict(FORM)
    session = FakeSession({FORM_URL: [response(200)]})
    client(session).post(FORM_URL, form)
    assert session.posted[0][1] == FORM and session.posted[0][1] is not form
