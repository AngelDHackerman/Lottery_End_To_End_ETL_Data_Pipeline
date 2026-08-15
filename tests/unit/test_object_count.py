"""Tests for the per-layer S3 object-count emitter (PR-035).

``loteria.observability.object_count`` answers a question the execution metrics cannot: is
the lake actually **growing**? A pipeline can go green every week while writing nothing —
the extractor re-scrapes a page it already has, the transformer skips the partition, every
stage succeeds and the object count never moves. That is invisible in ``AWS/States``.

So the two things worth pinning are that the counts are *right* (per prefix, past the 1000-
key page boundary) and that a publish failure never fails the invocation.
"""

from __future__ import annotations

import boto3
import pytest
from moto import mock_aws

from loteria.observability import object_count

REGION = "us-east-1"
BUCKET = "lottery-partitioned-storage-prod"


@pytest.fixture
def s3():
    with mock_aws():
        client = boto3.client("s3", region_name=REGION)
        client.create_bucket(Bucket=BUCKET)
        yield client


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("TARGET_BUCKET", BUCKET)
    monkeypatch.setenv("LAYER_PREFIXES", "raw/,silver/,gold/")
    monkeypatch.delenv("METRICS_NAMESPACE", raising=False)


@pytest.fixture
def published(monkeypatch):
    """Capture PutMetricData calls instead of making them."""
    calls = []

    class FakeCloudWatch:
        def put_metric_data(self, **kwargs):
            calls.append(kwargs)

    real_client = boto3.client

    def fake_client(service, *args, **kwargs):
        if service == "cloudwatch":
            return FakeCloudWatch()
        return real_client(service, *args, **kwargs)

    monkeypatch.setattr(object_count.boto3, "client", fake_client)
    return calls


def seed(s3, prefix, n, size=10):
    for i in range(n):
        s3.put_object(Bucket=BUCKET, Key=f"{prefix}file-{i:05d}.txt", Body=b"x" * size)


# ==========================================================================================
# Counting
# ==========================================================================================
class TestCountPrefix:
    def test_counts_objects_and_sums_their_bytes(self, s3):
        seed(s3, "raw/", n=3, size=10)

        assert object_count._count_prefix(s3, BUCKET, "raw/") == (3, 30)

    def test_an_empty_prefix_is_zero_not_an_error(self, s3):
        """A brand-new deployment has no gold/ yet, and a raise here would make the hourly
        Lambda red until the first pipeline run."""
        assert object_count._count_prefix(s3, BUCKET, "gold/") == (0, 0)

    def test_it_pages_past_the_thousand_key_limit(self, s3):
        """``list_objects_v2`` returns at most 1000 keys. Without the paginator this would
        silently plateau at exactly 1000 — a flat line that looks like a stalled pipeline
        rather than a bug in the thing measuring it."""
        seed(s3, "raw/", n=1001, size=1)

        count, total = object_count._count_prefix(s3, BUCKET, "raw/")
        assert count == 1001
        assert total == 1001

    def test_prefixes_do_not_bleed_into_each_other(self, s3):
        seed(s3, "raw/", n=2)
        seed(s3, "silver/", n=5)

        assert object_count._count_prefix(s3, BUCKET, "raw/")[0] == 2
        assert object_count._count_prefix(s3, BUCKET, "silver/")[0] == 5


# ==========================================================================================
# Publishing
# ==========================================================================================
class TestPublish:
    def test_publishes_the_batch(self):
        sent = []

        class Fake:
            def put_metric_data(self, **kwargs):
                sent.append(kwargs)

        assert object_count._publish(Fake(), "NS", [{"MetricName": "X", "Value": 1}]) is True
        assert sent[0]["Namespace"] == "NS"

    def test_an_empty_batch_is_a_no_op(self):
        """PutMetricData rejects an empty MetricData list, so an unconfigured LAYER_PREFIXES
        would turn into a hard error instead of a quiet nothing."""

        class Fake:
            def put_metric_data(self, **kwargs):
                raise AssertionError("should not be called")

        assert object_count._publish(Fake(), "NS", []) is True

    def test_a_publish_failure_is_swallowed(self):
        """Same contract as loteria.common.metrics. At worst this costs a missing dot on a
        graph; raising would cost a red invocation and a noisy Lambda error metric."""

        class Fake:
            def put_metric_data(self, **kwargs):
                raise RuntimeError("throttled")

        assert object_count._publish(Fake(), "NS", [{"MetricName": "X"}]) is False


# ==========================================================================================
# The handler
# ==========================================================================================
class TestHandler:
    def test_returns_counts_per_layer(self, s3, env, published):
        seed(s3, "raw/", n=3)
        seed(s3, "silver/", n=2)

        result = object_count.handler({}, None)

        assert result["layers"]["raw"]["objects"] == 3
        assert result["layers"]["silver"]["objects"] == 2
        assert result["layers"]["gold"]["objects"] == 0

    def test_the_layer_dimension_drops_the_trailing_slash(self, s3, env, published):
        """ "raw/" is what S3 needs; "raw" is what reads well in a dashboard legend and an
        alarm name."""
        seed(s3, "raw/", n=1)
        object_count.handler({}, None)

        layers = {
            d["Value"]
            for call in published
            for datum in call["MetricData"]
            for d in datum["Dimensions"]
        }
        assert layers == {"raw", "silver", "gold"}

    def test_it_publishes_two_metrics_per_layer(self, s3, env, published):
        """Bytes come from the same response as the count, so they are free — and they are
        what distinguishes "we wrote a file" from "we wrote a file with data in it"."""
        object_count.handler({}, None)

        names = [d["MetricName"] for call in published for d in call["MetricData"]]
        assert names.count(object_count.METRIC_OBJECT_COUNT) == 3
        assert names.count(object_count.METRIC_BYTES_STORED) == 3

    def test_everything_goes_in_one_api_call(self, s3, env, published):
        """PutMetricData accepts up to 1000 datapoints; batching keeps this to one request
        no matter how many prefixes are configured."""
        object_count.handler({}, None)

        assert len(published) == 1

    def test_the_default_namespace_matches_the_shared_constant(self, s3, env, published):
        """⚠️ A mismatch fails SILENTLY: the IAM policy scopes PutMetricData with a
        `cloudwatch:namespace` condition, and this module swallows publish errors. So the
        metrics would simply never appear, with nothing red anywhere."""
        from loteria.common.metrics import NAMESPACE

        assert object_count.DEFAULT_NAMESPACE == NAMESPACE

        object_count.handler({}, None)
        assert published[0]["Namespace"] == NAMESPACE

    def test_the_namespace_can_be_overridden(self, s3, env, published, monkeypatch):
        monkeypatch.setenv("METRICS_NAMESPACE", "Custom/NS")
        object_count.handler({}, None)

        assert published[0]["Namespace"] == "Custom/NS"

    def test_blank_entries_in_layer_prefixes_are_ignored(self, s3, env, published, monkeypatch):
        """A trailing comma in the Terraform variable is easy to leave behind, and an empty
        prefix would count the WHOLE bucket as a layer named "root"."""
        monkeypatch.setenv("LAYER_PREFIXES", "raw/,,silver/,")
        result = object_count.handler({}, None)

        assert set(result["layers"]) == {"raw", "silver"}

    def test_a_publish_failure_still_returns_the_counts(self, s3, env, monkeypatch):
        """The return value doubles as a readable smoke test for a manual invoke, so it has
        to survive a telemetry failure."""
        real_client = boto3.client

        class Fake:
            def put_metric_data(self, **kwargs):
                raise RuntimeError("throttled")

        monkeypatch.setattr(
            object_count.boto3,
            "client",
            lambda s, *a, **k: Fake() if s == "cloudwatch" else real_client(s, *a, **k),
        )
        seed(s3, "raw/", n=1)

        result = object_count.handler({}, None)

        assert result["published"] is False
        assert result["layers"]["raw"]["objects"] == 1

    def test_a_missing_target_bucket_raises(self, s3, monkeypatch):
        """Deliberately NOT defaulted. A typo'd env var silently counting the wrong bucket
        would produce a plausible graph of the wrong thing."""
        monkeypatch.delenv("TARGET_BUCKET", raising=False)
        monkeypatch.setenv("LAYER_PREFIXES", "raw/")

        with pytest.raises(KeyError):
            object_count.handler({}, None)
