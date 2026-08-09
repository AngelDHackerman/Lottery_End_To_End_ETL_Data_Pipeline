"""Publish per-medallion-layer S3 object counts as CloudWatch custom metrics (PR-027).

PR-024's dashboard covers *execution* health — did the run succeed, how long did each stage
take, what did Athena scan. What it cannot show is whether the lake is actually **growing**.
A pipeline can go green every week while writing nothing: the extractor scrapes a page it
has already scraped, the transformer rewrites the same partition, every stage succeeds and
the object count never moves. That failure is invisible in `AWS/States`.

So this Lambda counts the objects under each medallion prefix once an hour and publishes
them as ``ObjectCount`` / ``BytesStored``, dimensioned by ``Layer`` (``raw``, ``silver``,
``gold``). Plotted over 28 days, a flat raw/ line next to green executions is the signature
of a pipeline that is running but not ingesting.

**Why a Lambda at all.** S3 already publishes ``NumberOfObjects`` and ``BucketSizeBytes``
for free in ``AWS/S3`` — but only per *bucket* (optionally per storage class), never per
prefix. The medallion layers all live in one bucket, so the free metrics cannot tell raw/
from silver/ from gold/. Counting by hand is the only way to get the breakdown.

**Cost shape.** ``list_objects_v2`` returns up to 1000 keys per request and the largest
prefix here holds a few hundred, so a run is 3 LIST calls — well under a cent a month at
hourly cadence. This stays true only while the lake is small; see the note on
``_count_prefix`` for what to do when it is not.

Environment (all set by terraform/modules/observability):
    ``TARGET_BUCKET``      bucket holding the medallion prefixes
    ``LAYER_PREFIXES``     comma-separated, e.g. ``raw/,silver/,gold/``
    ``METRICS_NAMESPACE``  CloudWatch namespace (must match the IAM condition — see below)
"""

from __future__ import annotations

import logging
import os

import boto3

logger = logging.getLogger("loteria.observability.object_count")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format='{"level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
    )

# Read from the environment rather than importing loteria.common.metrics.NAMESPACE: this
# Lambda ships as a single file (no package), the same way the gold-purge Lambda does.
#
# The default MUST equal loteria.common.metrics.NAMESPACE and the iam module's
# `metrics_namespace`. A mismatch fails SILENTLY — the IAM policy scopes PutMetricData with
# a `cloudwatch:namespace` condition, so publishing to the wrong namespace is denied, and
# this module swallows publish errors on purpose (see `_publish`). Terraform passes the same
# variable to both the policy and this function, so they cannot drift in practice; the
# default is only a fallback for a local run.
DEFAULT_NAMESPACE = "Loteria/Pipeline"

METRIC_OBJECT_COUNT = "ObjectCount"
METRIC_BYTES_STORED = "BytesStored"


def _count_prefix(s3, bucket: str, prefix: str) -> tuple[int, int]:
    """Return ``(object_count, total_bytes)`` for every key under ``prefix``.

    Paginated, so it is correct past 1000 keys — but it is still O(objects), and at some
    lake size an hourly full scan stops being sensible. The replacement at that point is S3
    Inventory (a daily manifest) rather than a bigger timeout; ``ObjectCount`` is a slow-
    moving number and this pipeline writes once a week.

    Bytes come from the same response as the count, so they are free: no extra API call, no
    extra latency. They earn their (small) metric cost by distinguishing "we wrote a file"
    from "we wrote a file with data in it" — a truncated scrape still produces an object.
    """
    count = 0
    total_bytes = 0

    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        contents = page.get("Contents", [])
        count += len(contents)
        total_bytes += sum(obj["Size"] for obj in contents)

    return count, total_bytes


def _publish(cloudwatch, namespace: str, data: list[dict]) -> bool:
    """Publish a batch of datapoints. Never raises.

    Same contract as ``loteria.common.metrics``: telemetry must not be able to break the
    thing it observes. Here the stakes are lower (nothing downstream depends on this
    Lambda), but an exception would still mean a red invocation and a noisy Lambda error
    metric for what is, at worst, a missing dot on a graph.
    """
    if not data:
        return True

    try:
        # One call for every layer x metric: PutMetricData accepts up to 1000 datapoints,
        # and batching keeps this to a single request regardless of how many prefixes are
        # configured.
        cloudwatch.put_metric_data(Namespace=namespace, MetricData=data)
        return True
    except Exception:
        logger.warning(
            "Failed to publish S3 layer metrics (ignored)",
            exc_info=True,
            extra={"namespace": namespace, "datapoints": len(data)},
        )
        return False


def handler(event, context):  # noqa: ARG001 - Lambda signature
    """Count each configured prefix and publish the results.

    Invoked hourly by an EventBridge rule; the event is ignored. Returns the counts so a
    manual ``aws lambda invoke`` doubles as a readable smoke test.
    """
    bucket = os.environ["TARGET_BUCKET"]
    namespace = os.environ.get("METRICS_NAMESPACE", DEFAULT_NAMESPACE)
    prefixes = [p.strip() for p in os.environ["LAYER_PREFIXES"].split(",") if p.strip()]

    s3 = boto3.client("s3")
    cloudwatch = boto3.client("cloudwatch")

    data: list[dict] = []
    counts: dict[str, dict[str, int]] = {}

    for prefix in prefixes:
        # "raw/" -> "raw". The trailing slash is what S3 needs; the bare word is what reads
        # well in a dashboard legend and an alarm name.
        layer = prefix.strip("/") or "root"
        count, total_bytes = _count_prefix(s3, bucket, prefix)
        counts[layer] = {"objects": count, "bytes": total_bytes}

        dimensions = [{"Name": "Layer", "Value": layer}]
        data.append(
            {
                "MetricName": METRIC_OBJECT_COUNT,
                "Dimensions": dimensions,
                "Value": count,
                "Unit": "Count",
            }
        )
        data.append(
            {
                "MetricName": METRIC_BYTES_STORED,
                "Dimensions": dimensions,
                "Value": total_bytes,
                "Unit": "Bytes",
            }
        )

        logger.info(
            "layer=%s objects=%d bytes=%d bucket=%s prefix=%s",
            layer,
            count,
            total_bytes,
            bucket,
            prefix,
        )

    published = _publish(cloudwatch, namespace, data)

    return {"bucket": bucket, "namespace": namespace, "published": published, "layers": counts}
