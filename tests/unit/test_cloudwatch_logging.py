"""Tests for the direct CloudWatch Logs handler (PR-033.1).

This handler exists because PR-033's per-job log group came up **empty** on the first real
run: continuous logging carries Spark's log4j output, and the DQ job never starts Spark. The
group is now written to directly, which moves logging onto the job's critical path — so the
contract worth testing is less "does it log" than "what happens when it cannot".

Two properties matter more than the happy path:

1. **It never raises.** A CloudWatch throttle, outage or revoked permission must not fail a
   data-quality run. A gate that goes red for reasons unrelated to data teaches people to
   ignore it, which is the PR-031 canary lesson.
2. **It never creates the log group.** Terraform owns the group *and its retention*. A group
   created by application code defaults to "never expire" and becomes a silent permanent
   bill — the drift PR-023 exists to prevent.
"""

from __future__ import annotations

import logging

import boto3
import pytest
from moto import mock_aws

from loteria.common.cloudwatch_logging import (
    SELF_AMPLIFYING_LOGGERS,
    CloudWatchLogHandler,
    attach_cloudwatch_handler,
    quiet_sdk_loggers,
)

GROUP = "/aws-glue/jobs/loteria-silver-dq-prod"
STREAM = "lottery-etl-pipeline-prod-run-42"


def record(message: str = "hello", level: int = logging.INFO) -> logging.LogRecord:
    return logging.LogRecord(
        name="silver-dq",
        level=level,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )


class FakeLogsClient:
    """Records calls; optionally fails one of them."""

    def __init__(self, fail_on: str | None = None, error: Exception | None = None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._fail_on = fail_on
        self._error = error or RuntimeError("boom")

    def _maybe_fail(self, op: str) -> None:
        if self._fail_on == op:
            raise self._error

    def create_log_group(self, **kwargs):
        self.calls.append(("create_log_group", kwargs))
        self._maybe_fail("create_log_group")

    def create_log_stream(self, **kwargs):
        self.calls.append(("create_log_stream", kwargs))
        self._maybe_fail("create_log_stream")

    def put_log_events(self, **kwargs):
        self.calls.append(("put_log_events", kwargs))
        # PR-033.2: recorded first, then rejected, so a test can see the empty call that the
        # real API only reports as a ParamValidationError. This is the bug that left the prod
        # group with a stream and zero events; before this line the fake happily accepted it.
        if not kwargs.get("logEvents"):
            raise ParamValidation(
                "Parameter validation failed: Invalid length for parameter logEvents, "
                "value: 0, valid min length: 1"
            )
        self._maybe_fail("put_log_events")

    def ops(self) -> list[str]:
        return [name for name, _ in self.calls]


class AlreadyExists(Exception):
    """Stands in for botocore's runtime-minted ResourceAlreadyExistsException.

    Matched by class NAME in the handler, because botocore builds these types on the client
    at runtime and there is nothing importable to catch.
    """


AlreadyExists.__name__ = "ResourceAlreadyExistsException"


class ParamValidation(Exception):
    """Stands in for botocore's ParamValidationError, raised before anything is sent."""


class ChattyLogsClient(FakeLogsClient):
    """A client that logs while it works — which is what boto3 does, not a contrivance.

    The real run of 2026-09-20 recorded ~180 ``botocore.credentials`` records in 96 seconds.
    With the handler on the root logger, every one of them is a new record to ship, arriving
    while a send is already in flight. A fake that stays silent cannot see that at all, which
    is precisely why the PR-033.1 suite was green against a broken handler.
    """

    def __init__(self, chatter: int = 3, **kwargs) -> None:
        super().__init__(**kwargs)
        self._chatter = chatter

    def _talk(self) -> None:
        for _ in range(self._chatter):
            logging.getLogger("botocore.credentials").info("Found credentials from IAM Role")

    def create_log_stream(self, **kwargs):
        self._talk()
        super().create_log_stream(**kwargs)

    def put_log_events(self, **kwargs):
        try:
            super().put_log_events(**kwargs)
        finally:
            self._talk()

    def batches(self) -> list[list[dict]]:
        return [kwargs["logEvents"] for name, kwargs in self.calls if name == "put_log_events"]


class TestHappyPath:
    def test_the_record_reaches_the_named_group_and_stream(self):
        client = FakeLogsClient()
        handler = CloudWatchLogHandler(GROUP, STREAM, client=client)
        handler.setFormatter(logging.Formatter("%(message)s"))

        handler.emit(record("the verdict"))

        assert client.ops() == ["create_log_stream", "put_log_events"]
        _, put = client.calls[1]
        assert put["logGroupName"] == GROUP
        assert put["logStreamName"] == STREAM
        assert [e["message"] for e in put["logEvents"]] == ["the verdict"]

    def test_the_stream_is_created_once_not_per_record(self):
        client = FakeLogsClient()
        handler = CloudWatchLogHandler(GROUP, STREAM, client=client)
        handler.setFormatter(logging.Formatter("%(message)s"))

        for i in range(3):
            handler.emit(record(f"line {i}"))

        assert client.ops().count("create_log_stream") == 1
        assert client.ops().count("put_log_events") == 3

    def test_an_existing_stream_is_not_an_error(self):
        client = FakeLogsClient(fail_on="create_log_stream", error=AlreadyExists())
        handler = CloudWatchLogHandler(GROUP, STREAM, client=client)
        handler.setFormatter(logging.Formatter("%(message)s"))

        handler.emit(record())

        # Re-running the job with the same correlation id must keep logging, not stop.
        assert "put_log_events" in client.ops()

    def test_multiline_verdict_travels_as_one_event(self):
        # The whole reason the group gets a plain formatter rather than the JSON one.
        client = FakeLogsClient()
        handler = CloudWatchLogHandler(GROUP, STREAM, client=client)
        handler.setFormatter(logging.Formatter("%(message)s"))

        handler.emit(record("[PASS] silver_sorteos\n[PASS] silver_premios\n\nDQ RESULT: PASS"))

        _, put = client.calls[1]
        assert len(put["logEvents"]) == 1
        assert put["logEvents"][0]["message"].count("\n") == 3


class TestItNeverRaises:
    """Property 1. Each of these would otherwise fail a green data-quality run."""

    @pytest.mark.parametrize("failing_op", ["create_log_stream", "put_log_events"])
    def test_a_failing_api_call_does_not_propagate(self, failing_op):
        client = FakeLogsClient(fail_on=failing_op)
        handler = CloudWatchLogHandler(GROUP, STREAM, client=client)
        handler.setFormatter(logging.Formatter("%(message)s"))

        handler.emit(record())  # must not raise

    def test_it_disables_itself_after_a_failure_instead_of_retrying_forever(self, capsys):
        client = FakeLogsClient(fail_on="put_log_events")
        handler = CloudWatchLogHandler(GROUP, STREAM, client=client)
        handler.setFormatter(logging.Formatter("%(message)s"))

        for _ in range(5):
            handler.emit(record())

        # One attempt, then silence — not five round trips against a failing endpoint.
        assert client.ops().count("put_log_events") == 1
        # And it says so once, on stderr, which does reach /aws-glue/jobs/error.
        assert "disabled" in capsys.readouterr().err

    def test_a_broken_formatter_does_not_propagate(self, capsys):
        client = FakeLogsClient()
        handler = CloudWatchLogHandler(GROUP, STREAM, client=client)
        handler.setFormatter(logging.Formatter("%(nonexistent)s"))

        handler.emit(record())

        assert "disabled" in capsys.readouterr().err
        assert client.ops() == []

    def test_close_flushes_without_raising_when_the_client_is_broken(self):
        client = FakeLogsClient(fail_on="put_log_events")
        handler = CloudWatchLogHandler(GROUP, STREAM, client=client)
        handler.setFormatter(logging.Formatter("%(message)s"))
        handler.emit(record())

        handler.close()  # must not raise


class TestItNeverCreatesTheGroup:
    """Property 2. Terraform owns the group and its retention."""

    def test_the_group_is_never_created(self):
        client = FakeLogsClient()
        handler = CloudWatchLogHandler(GROUP, STREAM, client=client)
        handler.setFormatter(logging.Formatter("%(message)s"))

        handler.emit(record())

        assert "create_log_group" not in client.ops()

    def test_a_missing_group_disables_the_handler_rather_than_creating_it(self, capsys):
        missing = type("ResourceNotFoundException", (Exception,), {})()
        client = FakeLogsClient(fail_on="create_log_stream", error=missing)
        handler = CloudWatchLogHandler(GROUP, STREAM, client=client)
        handler.setFormatter(logging.Formatter("%(message)s"))

        handler.emit(record())

        assert "create_log_group" not in client.ops()
        assert "disabled" in capsys.readouterr().err


class TestAttach:
    def test_no_group_means_no_handler(self):
        root = logging.getLogger()
        before = list(root.handlers)

        assert attach_cloudwatch_handler(None, STREAM) is None
        assert attach_cloudwatch_handler("", STREAM) is None

        # The normal case outside Glue (`make dq`, this test suite) must leave logging alone.
        assert list(root.handlers) == before

    def test_attaching_adds_exactly_one_handler_to_the_root_logger(self):
        root = logging.getLogger()
        before = list(root.handlers)
        client = FakeLogsClient()
        try:
            handler = attach_cloudwatch_handler(GROUP, STREAM, client=client)
            assert handler is not None
            assert root.handlers == [*before, handler]
        finally:
            root.handlers = before

    def test_the_group_formatter_is_readable_not_json(self):
        client = FakeLogsClient()
        root = logging.getLogger()
        before = list(root.handlers)
        try:
            handler = attach_cloudwatch_handler(GROUP, STREAM, client=client)
            handler.emit(record("DQ RESULT: PASS"))
        finally:
            root.handlers = before

        _, put = client.calls[1]
        message = put["logEvents"][0]["message"]
        assert "DQ RESULT: PASS" in message
        assert not message.startswith("{")


class TestAgainstMoto:
    """One end-to-end pass against a real API shape, so the fake cannot drift from boto3."""

    def test_events_land_in_the_group(self):
        with mock_aws():
            logs = boto3.client("logs", region_name="us-east-1")
            logs.create_log_group(logGroupName=GROUP)  # Terraform's job, done here by hand

            handler = CloudWatchLogHandler(GROUP, STREAM, client=logs)
            handler.setFormatter(logging.Formatter("%(message)s"))
            handler.emit(record("DQ RESULT: PASS"))
            handler.close()

            events = logs.get_log_events(logGroupName=GROUP, logStreamName=STREAM)["events"]
            assert [e["message"] for e in events] == ["DQ RESULT: PASS"]


@pytest.fixture
def root_logging_restored():
    """Hand back the root logger and the SDK loggers exactly as they were.

    These tests put a handler on the root logger on purpose — that is where the bug lives —
    and `quiet_sdk_loggers` mutates global logger levels, so nothing here may leak into the
    next test.
    """
    root = logging.getLogger()
    handlers, root_level = list(root.handlers), root.level
    sdk_levels = {name: logging.getLogger(name).level for name in SELF_AMPLIFYING_LOGGERS}
    root.setLevel(logging.INFO)  # so an INFO record from the SDK actually reaches a handler
    try:
        yield root
    finally:
        root.handlers, root.level = handlers, root_level
        for name, level in sdk_levels.items():
            logging.getLogger(name).setLevel(level)


class TestItDoesNotFeedItself:
    """PR-033.2. The handler calls AWS; AWS logs; the handler is on the root logger.

    The prod symptom was a log group holding one stream and zero events, with eight
    `[cloudwatch-logging] disabled ... Invalid length for parameter logEvents, value: 0`
    lines on stderr. Every test here fails against the PR-033.1 handler.
    """

    def test_sdk_chatter_during_a_send_does_not_empty_the_batch(self, root_logging_restored):
        client = ChattyLogsClient()
        handler = CloudWatchLogHandler(GROUP, STREAM, client=client)
        handler.setFormatter(logging.Formatter("%(message)s"))
        root_logging_restored.addHandler(handler)

        logging.getLogger("silver-dq").info("DQ RESULT: PASS")

        assert client.batches(), "nothing was sent at all"
        assert all(batch for batch in client.batches()), "PutLogEvents called with []"
        assert not handler._disabled

    def test_the_verdict_still_reaches_the_group(self, root_logging_restored):
        client = ChattyLogsClient()
        handler = CloudWatchLogHandler(GROUP, STREAM, client=client)
        handler.setFormatter(logging.Formatter("%(message)s"))
        root_logging_restored.addHandler(handler)

        logging.getLogger("silver-dq").info("DQ RESULT: PASS")

        sent = [event["message"] for batch in client.batches() for event in batch]
        assert "DQ RESULT: PASS" in sent

    def test_records_arriving_mid_send_are_kept_not_dropped(self, root_logging_restored):
        client = ChattyLogsClient(chatter=2)
        handler = CloudWatchLogHandler(GROUP, STREAM, client=client)
        handler.setFormatter(logging.Formatter("%(message)s"))
        root_logging_restored.addHandler(handler)

        logging.getLogger("silver-dq").info("first")
        # The chatter from the first send sits at the back of the buffer; this one carries it
        # out. Losing it would be a quieter bug than the crash, and just as wrong.
        logging.getLogger("silver-dq").info("second")

        sent = [event["message"] for batch in client.batches() for event in batch]
        assert sent.count("Found credentials from IAM Role") >= 2
        assert "first" in sent and "second" in sent

    def test_it_says_disabled_once_not_once_per_nested_frame(self, root_logging_restored, capsys):
        client = ChattyLogsClient(fail_on="put_log_events")
        handler = CloudWatchLogHandler(GROUP, STREAM, client=client)
        handler.setFormatter(logging.Formatter("%(message)s"))
        root_logging_restored.addHandler(handler)

        logging.getLogger("silver-dq").info("DQ RESULT: PASS")

        assert capsys.readouterr().err.count("[cloudwatch-logging] disabled") == 1

    def test_a_hand_flush_with_an_empty_buffer_sends_nothing(self):
        client = FakeLogsClient()
        handler = CloudWatchLogHandler(GROUP, STREAM, client=client)

        handler.flush()

        assert client.ops() == []
        assert not handler._disabled


class TestQuietSdkLoggers:
    def test_attaching_quiets_the_sdk_loggers(self, root_logging_restored):
        logging.getLogger("botocore").setLevel(logging.NOTSET)

        attach_cloudwatch_handler(GROUP, STREAM, client=FakeLogsClient())

        # INFO under a root at INFO is what produced ~180 credential records in one run.
        assert not logging.getLogger("botocore.credentials").isEnabledFor(logging.INFO)
        assert logging.getLogger("botocore.credentials").isEnabledFor(logging.WARNING)

    def test_a_logger_already_quieter_is_left_alone(self, root_logging_restored):
        logging.getLogger("botocore").setLevel(logging.ERROR)

        quiet_sdk_loggers()

        # Silencing is a floor, not an assignment: a caller who wanted less keeps less.
        assert logging.getLogger("botocore").level == logging.ERROR

    def test_no_group_means_no_global_side_effect(self, root_logging_restored):
        logging.getLogger("botocore").setLevel(logging.NOTSET)

        assert attach_cloudwatch_handler(None, STREAM) is None

        # `make dq` and this test suite go through here. Neither asked for quieter logs.
        assert logging.getLogger("botocore").level == logging.NOTSET
