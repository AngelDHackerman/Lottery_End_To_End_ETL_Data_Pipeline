"""Ship a process's log records straight to one CloudWatch Logs group (PR-033.1).

**Why this exists.** PR-033 gave the Silver DQ job its own log group and asked Glue to fill
it with ``--enable-continuous-cloudwatch-log`` + ``--continuous-log-logGroup``. The first
real run (2026-09-16) proved that does not work *for this job*: the group had **zero**
streams, and every line — the JSON logs and the ``DQ RESULT`` verdict alike — landed in the
account-wide ``/aws-glue/jobs/output``.

The reason is a consequence of the job's own design rather than a misconfiguration.
Continuous logging ships **Spark's log4j output**, and ``loteria.dq.glue_entrypoint``
deliberately never creates a ``SparkContext`` — it runs as an ordinary Python process on the
driver, because the Spark cluster is only there to supply Python 3.11. No Spark, no log4j,
nothing for continuous logging to carry. ``JobRun.LogGroupName`` reporting the base
``/aws-glue/jobs`` rather than the configured group is the tell.

So the group has to be written to directly, which is all this module does.

**What it deliberately does not do.**

- **It never creates the log group.** Terraform owns it, together with its retention. A
  group conjured by application code comes with retention "never expire" and silently
  becomes a permanent bill — the drift PR-023 exists to prevent. A missing group disables
  this handler instead.
- **It never raises.** Logging is not this job's purpose. A CloudWatch outage, a throttle or
  a revoked permission must not turn a green data-quality run red; the handler disables
  itself, says so once on stderr (which *does* reach ``/aws-glue/jobs/error``), and the
  process carries on with its stdout logging intact.

**PR-033.2 — a logging handler that calls AWS feeds itself.** The first prod run of the fix
above left the group with a stream and *zero events*: the handler had disabled itself eight
times over with ``Invalid length for parameter logEvents, value: 0``. The cause is that this
handler sits on the **root** logger and its own boto3 calls log — ``botocore.credentials``
alone emitted ~180 records in a 96-second run. Each of those came back into :meth:`emit`
*while a send was in flight*, and the nested flush emptied the buffer under the outer
frame's feet, which then called PutLogEvents with ``[]``. Two things answer it, and both are
held by tests:

- :attr:`CloudWatchLogHandler._sending` makes a nested flush a no-op, so a send always owns
  the buffer it sliced. Records that arrive mid-send ride out with the next one.
- :func:`quiet_sdk_loggers` raises the AWS SDK loggers to ``WARNING``. Without it the
  feedback loop is merely *bounded* rather than broken, and the group fills with credential
  chatter — which defeats the point of a group whose whole job is that a woken-up human can
  find one verdict in it.
"""

from __future__ import annotations

import logging
import sys

#: Readable, not JSON. stdout keeps the machine-parseable envelope from
#: ``loteria.common.logging_setup``; this group exists so a human can read a verdict after an
#: alert, and escaped ``\n`` inside a JSON string is the opposite of that.
DEFAULT_MESSAGE_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"

#: PutLogEvents caps a batch at 10,000 events / 1 MiB. This job emits a handful per run, so
#: the cap is a guard against a future caller, not a constraint this one can reach.
MAX_BATCH_EVENTS = 1_000


class CloudWatchLogHandler(logging.Handler):
    """A ``logging.Handler`` that writes to one CloudWatch Logs stream, or to nothing.

    Records are sent as they arrive rather than buffered to a timer. The job emits about six
    of them per run, so the extra API calls are free, and the alternative loses the tail:
    when the gate fails it raises, and the most valuable lines are the last ones.
    """

    def __init__(
        self,
        log_group: str,
        log_stream: str,
        client=None,  # noqa: ANN001 - a boto3 client, typed only by duck
        level: int = logging.NOTSET,
    ) -> None:
        super().__init__(level=level)
        self.log_group = log_group
        self.log_stream = log_stream
        self._client = client
        self._stream_ready = False
        self._disabled = False
        self._sending = False
        self._buffer: list[dict] = []

    # -- internals ---------------------------------------------------------------------

    def _ensure_client(self):  # noqa: ANN202
        if self._client is None:
            import boto3  # imported lazily: this module must stay importable in a test run

            self._client = boto3.client("logs")
        return self._client

    def _ensure_stream(self) -> None:
        if self._stream_ready:
            return
        client = self._ensure_client()
        try:
            client.create_log_stream(logGroupName=self.log_group, logStreamName=self.log_stream)
        except Exception as exc:  # noqa: BLE001 - re-raised unless it is the benign one
            # Matched by name rather than by class: botocore mints these exception types on
            # the client at runtime, so there is nothing importable to catch here.
            if type(exc).__name__ != "ResourceAlreadyExistsException":
                raise
        self._stream_ready = True

    def _disable(self, reason: object) -> None:
        """Stop trying, once, loudly enough to be found and quietly enough to be ignored."""
        if self._disabled:
            # PR-033.2: the first prod run printed this eight times, because every frame of
            # the re-entrant stack below hit the same failure on the way out. Once means once.
            return
        self._disabled = True
        self._buffer.clear()
        print(
            f"[cloudwatch-logging] disabled for {self.log_group}/{self.log_stream}: {reason}. "
            "Logs continue on stdout.",
            file=sys.stderr,
        )

    # -- logging.Handler ---------------------------------------------------------------

    def emit(self, record: logging.LogRecord) -> None:
        if self._disabled:
            return
        try:
            self._buffer.append(
                {"timestamp": int(record.created * 1000), "message": self.format(record)}
            )
        except Exception as exc:  # noqa: BLE001 - a bad formatter must not kill the job
            self._disable(exc)
            return
        self.flush()

    def flush(self) -> None:
        # ``_sending`` is what makes this handler safe to put on the ROOT logger, which is
        # where attach_cloudwatch_handler puts it. See the module docstring: the boto3 calls
        # below emit log records of their own, those records come straight back here, and
        # without this guard the nested flush drains the buffer while the outer frame is
        # still inside ``_ensure_stream`` — leaving it to call PutLogEvents with an empty
        # batch, which is a ParamValidationError, which disables the handler. That is
        # exactly how the group came up empty again on 2026-09-20 (PR-033.2).
        #
        # Records that arrive during a send are not lost: they stay at the BACK of the
        # buffer, the outer frame deletes only the slice it sent (from the front), and the
        # next emit carries them out.
        if self._disabled or self._sending or not self._buffer:
            return
        self._sending = True
        try:
            self._ensure_stream()
            client = self._ensure_client()
            batch = self._buffer[:MAX_BATCH_EVENTS]
            if not batch:
                # Unreachable through emit() now that re-entrancy is guarded, and kept
                # anyway: PutLogEvents rejects an empty batch outright, so a future caller
                # that flushes by hand must not be able to turn that into a disabled handler.
                return
            client.put_log_events(
                logGroupName=self.log_group,
                logStreamName=self.log_stream,
                logEvents=batch,
            )
            # Dropped only after the call returns, so a failed send keeps its events for the
            # next attempt rather than losing them between the slice and the wire.
            del self._buffer[: len(batch)]
        except Exception as exc:  # noqa: BLE001 - see the module docstring
            self._disable(exc)
        finally:
            self._sending = False

    def close(self) -> None:
        try:
            self.flush()
        finally:
            super().close()


#: Loggers that this handler would otherwise feed back to itself: every one of them is
#: emitted by the AWS SDK machinery that the handler calls to ship a record. ``WARNING`` keeps
#: the failures ("credentials expired", a retry storm) and drops the running commentary.
SELF_AMPLIFYING_LOGGERS = ("boto3", "botocore", "urllib3", "s3transfer")


def quiet_sdk_loggers(level: int = logging.WARNING) -> None:
    """Raise the AWS SDK loggers to ``level``, never lower them (PR-033.2).

    Called by :func:`attach_cloudwatch_handler`, because it is attaching the handler that
    makes SDK chatter self-amplifying. A logger already set *quieter* than ``level`` is left
    alone — silencing is a floor here, not an assignment.
    """
    for name in SELF_AMPLIFYING_LOGGERS:
        logger = logging.getLogger(name)
        if logger.getEffectiveLevel() < level:
            logger.setLevel(level)


def attach_cloudwatch_handler(
    log_group: str | None,
    log_stream: str,
    client=None,  # noqa: ANN001
    level: int = logging.NOTSET,
) -> CloudWatchLogHandler | None:
    """Add a :class:`CloudWatchLogHandler` to the root logger, or do nothing.

    Returns ``None`` when ``log_group`` is empty — which is the normal case outside Glue
    (``make dq``, the test suite), so callers need no environment check of their own.

    Call this **after** ``loteria.common.logging_setup.configure_logging``: that function
    replaces the root handler list wholesale, so a handler added before it would be dropped.

    Attaching also quiets the AWS SDK loggers (:func:`quiet_sdk_loggers`) — a deliberate
    global side effect, because the loop it breaks is global: this handler is on the root
    logger, so every record the SDK emits becomes another record to ship. See PR-033.2 in
    the module docstring.
    """
    if not log_group:
        return None

    quiet_sdk_loggers()

    handler = CloudWatchLogHandler(log_group, log_stream, client=client, level=level)
    handler.setFormatter(logging.Formatter(DEFAULT_MESSAGE_FORMAT))
    logging.getLogger().addHandler(handler)
    return handler
