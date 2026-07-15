"""Structured JSON logging for the loteria pipeline (PR-018).

Every log line is emitted as a single JSON object so CloudWatch Logs Insights can query
by field, and every line in one pipeline run carries the same ``correlation_id`` — the
Step Function execution name — so the extractor (Lambda) and transformer (Glue) logs of a
single weekly run can be stitched together.

Entry points call :func:`configure_logging` on startup; library modules just do
``logger = logging.getLogger(__name__)`` and log normally — records propagate to the root
handler installed here and come out as JSON.

Implemented with the standard library only (no ``python-json-logger``) so nothing extra
has to be vendored into the Lambda zip or installed into the Glue job.
"""

import json
import logging
import os
import sys
import uuid

# Fields we always want, in a stable order. LogRecord attribute -> output key.
_STD_FIELDS = {
    "levelname": "level",
    "name": "logger",
    "message": "message",
}


class JsonFormatter(logging.Formatter):
    """Render a ``LogRecord`` as a one-line JSON object.

    Output keys: ``timestamp``, ``level``, ``logger``, ``message``, ``service``,
    ``correlation_id``. Any ``extra={...}`` passed to the logging call is merged in as
    additional top-level keys, and exception info is rendered under ``exc_info``.
    """

    def __init__(self, service: str, correlation_id: str) -> None:
        super().__init__()
        self._service = service
        self._correlation_id = correlation_id

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "service": self._service,
            "correlation_id": self._correlation_id,
        }

        # Merge any structured context passed via `extra={...}` (skip the standard
        # LogRecord attributes so we only pick up caller-supplied keys).
        for key, value in record.__dict__.items():
            if key not in _RESERVED_RECORD_KEYS and key not in payload:
                payload[key] = value

        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, default=str)


# Attributes present on a vanilla LogRecord — used to detect caller-supplied `extra` keys.
_RESERVED_RECORD_KEYS = set(vars(logging.makeLogRecord({})).keys()) | {"message", "asctime"}


def resolve_correlation_id() -> str:
    """Return the correlation id: ``CORRELATION_ID`` env var, else a fresh UUID.

    The Step Function sets ``CORRELATION_ID`` to its execution name for both the Lambda
    and the Glue job; a local/ad-hoc run falls back to a generated UUID.
    """
    return os.environ.get("CORRELATION_ID") or str(uuid.uuid4())


def configure_logging(service_name: str, level: int = logging.INFO) -> logging.Logger:
    """Install the JSON formatter on the root logger and return a service logger.

    Safe to call more than once (e.g. per Lambda invocation): it replaces the root
    handlers rather than stacking new ones, so the ``correlation_id`` is refreshed from
    the environment each time.
    """
    correlation_id = resolve_correlation_id()

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service_name, correlation_id))

    root = logging.getLogger()
    root.setLevel(level)
    # Replace any pre-existing handlers (Lambda installs its own; a stray basicConfig may
    # add one) so all output is JSON and not duplicated.
    root.handlers = [handler]

    return logging.getLogger(service_name)
