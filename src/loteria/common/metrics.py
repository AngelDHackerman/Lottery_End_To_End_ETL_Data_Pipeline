"""CloudWatch custom metrics for the loteria pipeline (PR-026).

Why this exists: the weekly scrape goes through **scrape.do**, a third-party proxy used on
its FREE tier. When that plan lapses or its quota is exhausted the proxy starts answering
401 / 402 / 429, and today that surfaces only as a generic "Lambda error" — the same signal
you would get from a parser bug or an S3 permission problem. Emitting the proxy's HTTP
status as a metric lets an alarm name the actual cause ("start paying / swap proxy")
instead of making someone read logs to find out.

Two metrics are published, and the split is deliberate:

``ScraperHttpStatus`` — dimension ``StatusCode``, value 1 per request.
    One time series per distinct code, which is what the dashboard breakdown needs.

``ScraperHttpErrors`` — **no dimensions**, value 1 per non-200 request.
    A CloudWatch alarm watches exactly one time series with one dimension set, so
    ``ScraperHttpStatus`` alone cannot express "alarm on ANY non-200" — you would have to
    enumerate every code you might ever receive, in advance. This dimensionless companion
    metric is a single alarmable series that PR-025's ``ScrapeDo_Failed`` alarm can target
    with a plain `>= 1` threshold.

**Nothing in this module ever raises.** Telemetry must not be able to break the pipeline it
observes: a throttled `PutMetricData`, a missing IAM grant or an expired credential would
otherwise turn a successful scrape into a failed run. Failures are logged and swallowed.
"""

import logging

import boto3

logger = logging.getLogger(__name__)

# Single namespace for every custom metric this project publishes (PR-027's per-layer S3
# object counts belong here too). It is a CONSTANT on purpose: the extractor's IAM policy
# scopes cloudwatch:PutMetricData with a `cloudwatch:namespace` condition, so an
# env-var-overridable value here would silently lose permission to publish.
NAMESPACE = "Loteria/Pipeline"

METRIC_HTTP_STATUS = "ScraperHttpStatus"
METRIC_HTTP_ERRORS = "ScraperHttpErrors"


def put_metric(
    metric_name: str,
    value: float = 1.0,
    unit: str = "Count",
    dimensions: dict[str, str] | None = None,
) -> bool:
    """Publish one datapoint to ``NAMESPACE``. Returns True on success, False on failure.

    Never raises — see the module docstring. The return value is for callers that want to
    know (and for tests); the pipeline itself ignores it.
    """
    datum: dict = {"MetricName": metric_name, "Value": value, "Unit": unit}
    if dimensions:
        datum["Dimensions"] = [{"Name": k, "Value": str(v)} for k, v in dimensions.items()]

    try:
        # Client built here rather than at import time: this module is imported by
        # scraping.py, and an import-time client would make a credential problem a
        # module-import failure instead of a swallowed telemetry failure.
        boto3.client("cloudwatch").put_metric_data(Namespace=NAMESPACE, MetricData=[datum])
        return True
    except Exception:
        # Deliberately broad: ClientError, EndpointConnectionError, NoCredentialsError and
        # anything botocore invents later must all be non-fatal here.
        logger.warning(
            "Failed to publish CloudWatch metric (ignored)",
            exc_info=True,
            extra={"metric_name": metric_name, "namespace": NAMESPACE},
        )
        return False


def record_scraper_status(status_code: int) -> None:
    """Record the outcome of one scrape.do request.

    Always emits ``ScraperHttpStatus`` (dimensioned by code); additionally emits the
    dimensionless ``ScraperHttpErrors`` when the code is not 200 so an alarm has a single
    series to watch. Call this BEFORE raising on a non-200, or the failure that most needs
    a datapoint is the one that never produces one.
    """
    put_metric(METRIC_HTTP_STATUS, dimensions={"StatusCode": str(status_code)})

    if status_code != 200:
        put_metric(METRIC_HTTP_ERRORS)
