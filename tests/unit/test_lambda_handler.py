"""The extractor's Lambda entry point (PR-035).

Thirteen statements that had never been executed by a test, sitting at the edge where the
Step Function hands over to Python. Three of them carry contracts nothing else checks: the
payload shape the state machine sends, the correlation id that stitches this invocation's
logs to the Glue job's, and the fact that a scrape failure is allowed to propagate.

Rescued from `origin/feat/PR-035-coverage-85`; ``lambda_handler.py`` has not changed since it
was written, so the tests are as they were.
"""

from __future__ import annotations

import importlib
import os
import sys

import pytest

PARTITIONED = "test-partitioned-bucket"
SIMPLE = "test-simple-bucket"
TOKEN = "test-token"


@pytest.fixture
def handler(monkeypatch):
    """Import the handler with the import chain's Secrets Manager call neutralised.

    ``lambda_handler`` imports ``scraping``, which reads its buckets and token at import
    time — so the patch has to be in place before either module is loaded.
    """
    import loteria.common.aws_secrets as aws_secrets

    monkeypatch.setattr(
        aws_secrets,
        "get_secrets",
        lambda: {"partitioned": PARTITIONED, "simple": SIMPLE, "scrape_do_token": TOKEN},
    )
    sys.modules.pop("loteria.extractor.scraping", None)
    sys.modules.pop("loteria.extractor.lambda_handler", None)

    module = importlib.import_module("loteria.extractor.lambda_handler")
    monkeypatch.setattr(module, "extract_lottery_data", lambda n: f"/tmp/sorteo_{n}.txt")

    yield module

    sys.modules.pop("loteria.extractor.scraping", None)
    sys.modules.pop("loteria.extractor.lambda_handler", None)


class TestLambdaHandler:
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

        assert os.environ["CORRELATION_ID"] == "exec-7"

    def test_a_skipped_sorteo_still_returns_ok_with_a_null_file(self, handler, monkeypatch):
        """``extract_lottery_data`` returns None when it decides the draw is already
        processed. The state machine reads only ``status``, so the run continues to the
        transformer — which then finds nothing new and does nothing. That chain is the
        design, not an accident, and it is the reason a skip is not an error."""
        monkeypatch.setattr(handler, "extract_lottery_data", lambda n: None)

        assert handler.lambda_handler({}, None) == {"status": "ok", "file": None}

    def test_a_scrape_failure_propagates(self, handler, monkeypatch):
        """The Step Function's error handling depends on the invoke failing. Swallowing here
        would let the transformer run against a raw/ prefix nothing was added to."""

        def boom(_n):
            raise ValueError("❌ No se pudo encontrar el enlace al sorteo.")

        monkeypatch.setattr(handler, "extract_lottery_data", boom)

        with pytest.raises(ValueError):
            handler.lambda_handler({}, None)
