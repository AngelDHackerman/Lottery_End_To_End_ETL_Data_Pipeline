"""The polite client: privacy blocklist, retries, redirects, rate limit (UY-001)."""

from __future__ import annotations

import pytest
import requests
from requests.structures import CaseInsensitiveDict

from loteria_uy import http_client
from loteria_uy.http_client import (
    BlockedURLError,
    FetchError,
    PoliteClient,
    _RateLimiter,
    blocked_pattern,
)

# The three files the brief lists as EXCLUDED. Strings only: nothing here may fetch them.
EXCLUDED = [
    "https://www.loteria.gub.uy/invalidas/20160706/TDI_06072016_DET_INVALIDAS_GENERAL_TELEFONICAS.PDF",
    "https://www.loteria.gub.uy/invalidas/20160706/QDI_06072016_DET_INVALIDAS_GENERAL_TELEFONICAS.PDF",
    "https://www.loteria.gub.uy/invalidas/06072016/ORO_06072016_DET_INVALIDAS_GENERAL_TELEFONICAS.PDF",
]
POZOS = "https://www.loteria.gub.uy/invalidas/06072016/ORO_06072016_RES_INFORMACION_DE_POZOS.PDF"


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

    def get(self, url, timeout, allow_redirects):
        assert allow_redirects is False, "redirects must be followed by hand"
        self.calls.append(url)
        item = self.answers[url].pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def client(session, **kwargs) -> PoliteClient:
    kwargs.setdefault("sleep", lambda _s: None)
    return PoliteClient(session=session, **kwargs)


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
        PoliteClient(min_interval=0.5, session=FakeSession({}))


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
