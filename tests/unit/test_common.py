"""Tests for the shared helpers: secrets, S3 utilities and custom metrics (PR-035).

These three modules are small, sit underneath everything else, and were the last untested
code in ``loteria.common``. Two of them have a contract that is easy to state and easy to
break silently:

* ``metrics`` must **never raise** — telemetry that can fail the pipeline it observes is
  worse than no telemetry;
* ``aws_secrets`` must strip S3 ARNs down to bucket names, because the secret payload stores
  ARNs while every caller passes the result straight to boto3 as a ``Bucket=``.
"""

from __future__ import annotations

import json
import logging

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from loteria.common import aws_secrets, metrics, s3_utils

REGION = "us-east-1"
BUCKET = "test-bucket"


# ==========================================================================================
# aws_secrets
# ==========================================================================================
SECRET_PAYLOAD = {
    "s3_bucket_simple_data_storage_prod_arn": "arn:aws:s3:::lottery-data-simple-prod",
    "s3_bucket_partitioned_data_storage_prod_arn": "arn:aws:s3:::lottery-partitioned-storage-prod",
    "scrape_do_token": "a-token",
}


@pytest.fixture
def secretsmanager(monkeypatch):
    """A fake Secrets Manager holding the payload under a test-specific name."""
    with mock_aws():
        client = boto3.client("secretsmanager", region_name=REGION)

        def _create(payload=None, name="test-secret"):
            client.create_secret(Name=name, SecretString=json.dumps(payload or SECRET_PAYLOAD))
            monkeypatch.setenv("LOTERIA_SECRET_NAME", name)
            monkeypatch.setenv("AWS_REGION", REGION)
            return name

        yield _create


class TestBucketName:
    """``_bucket_name`` replaced a ``.split(":::")[-1]`` slice. These pin what that fixed."""

    def test_strips_a_plain_s3_arn(self):
        assert aws_secrets._bucket_name("arn:aws:s3:::my-bucket") == "my-bucket"

    def test_leaves_a_bare_bucket_name_alone(self):
        """The secret payload is supposed to migrate to bare names (there is a FOLLOW-UP note
        in the module), so both shapes have to keep working."""
        assert aws_secrets._bucket_name("my-bucket") == "my-bucket"

    @pytest.mark.parametrize("partition", ["aws-us-gov", "aws-cn"])
    def test_handles_other_aws_partitions(self, partition):
        assert aws_secrets._bucket_name(f"arn:{partition}:s3:::my-bucket") == "my-bucket"

    def test_does_not_mangle_a_value_that_merely_contains_the_separator(self):
        """The old `.split(":::")[-1]` returned "oops" for this. The regex is anchored, so a
        non-ARN string comes back untouched instead of being silently truncated."""
        assert aws_secrets._bucket_name("weird:::oops") == "weird:::oops"

    def test_an_arn_with_a_key_is_not_treated_as_a_bucket(self):
        """The pattern is anchored end-to-end, so an object ARN does not quietly yield a
        bucket name that would then be used as one."""
        value = "arn:aws:s3:::my-bucket/some/key"
        assert aws_secrets._bucket_name(value) == value


class TestGetSecrets:
    def test_returns_bucket_names_not_arns(self, secretsmanager):
        """Every caller passes these straight to boto3 as `Bucket=`, which rejects an ARN."""
        secretsmanager()
        result = aws_secrets.get_secrets()

        assert result["simple"] == "lottery-data-simple-prod"
        assert result["partitioned"] == "lottery-partitioned-storage-prod"

    def test_passes_the_scrape_token_through_verbatim(self, secretsmanager):
        secretsmanager()
        assert aws_secrets.get_secrets()["scrape_do_token"] == "a-token"

    def test_reads_the_secret_name_from_the_environment(self, secretsmanager):
        """PR-017: cloning into another account should mean changing one env var, not code."""
        secretsmanager(name="some-other-secret")
        assert aws_secrets.get_secrets()["simple"] == "lottery-data-simple-prod"

    def test_a_missing_secret_raises_rather_than_returning_empty(self, secretsmanager, monkeypatch):
        """This runs at module import in the extractor and the transformer. Returning a
        partial dict would surface much later as a confusing KeyError or, worse, as a write
        to a bucket named "None"."""
        secretsmanager()
        monkeypatch.setenv("LOTERIA_SECRET_NAME", "does-not-exist")

        with pytest.raises(ClientError):
            aws_secrets.get_secrets()


# ==========================================================================================
# s3_utils
# ==========================================================================================
@pytest.fixture
def s3():
    with mock_aws():
        client = boto3.client("s3", region_name=REGION)
        client.create_bucket(Bucket=BUCKET)
        yield client


class TestUploadToS3:
    def test_uploads_the_file_contents(self, s3, tmp_path):
        local = tmp_path / "results.txt"
        local.write_text("HEADER\nBODY\n", encoding="utf-8")

        s3_utils.upload_to_s3(str(local), BUCKET, "raw/results.txt")

        body = s3.get_object(Bucket=BUCKET, Key="raw/results.txt")["Body"].read()
        assert body.decode("utf-8") == "HEADER\nBODY\n"


class TestCheckIfSorteoExists:
    """The extractor's idempotency guard: a True here cancels the whole scrape."""

    def _key(self, year, sorteo, prefix="silver/sorteos/"):
        return f"{prefix}year={year}/sorteo={sorteo}/sorteos.parquet"

    def test_true_when_the_object_is_there(self, s3):
        s3.put_object(Bucket=BUCKET, Key=self._key(2024, 3046), Body=b"x")
        assert s3_utils.check_if_sorteo_exists(BUCKET, 2024, 3046) is True

    def test_false_when_it_is_not(self, s3):
        assert s3_utils.check_if_sorteo_exists(BUCKET, 2024, 3046) is False

    def test_a_different_year_is_a_different_sorteo(self, s3):
        """The key embeds both, so a year mismatch must not read as "already processed" —
        that would silently skip a real draw."""
        s3.put_object(Bucket=BUCKET, Key=self._key(2024, 3046), Body=b"x")
        assert s3_utils.check_if_sorteo_exists(BUCKET, 2025, 3046) is False

    def test_the_legacy_processed_prefix_is_not_consulted(self, s3):
        """PR-035.1 A: ``processed/`` is where this used to look, and nothing writes there."""
        s3.put_object(Bucket=BUCKET, Key=self._key(2024, 3046, "processed/"), Body=b"x")
        assert s3_utils.check_if_sorteo_exists(BUCKET, 2024, 3046) is False

    def test_the_prefix_can_be_overridden(self, s3):
        s3.put_object(Bucket=BUCKET, Key=self._key(2024, 3046, "other/"), Body=b"x")
        assert s3_utils.check_if_sorteo_exists(BUCKET, 2024, 3046, prefix="other/") is True

    def test_a_non_404_error_is_re_raised(self, monkeypatch):
        """Only "not found" means "not processed". Swallowing an AccessDenied would make a
        broken permission look like a fresh sorteo and re-scrape it every week."""

        class Boom:
            def head_object(self, **kwargs):
                raise ClientError({"Error": {"Code": "403", "Message": "Forbidden"}}, "HeadObject")

        monkeypatch.setattr(s3_utils.boto3, "client", lambda *_a, **_k: Boom())

        with pytest.raises(ClientError):
            s3_utils.check_if_sorteo_exists(BUCKET, 2024, 3046)


# ==========================================================================================
# metrics
# ==========================================================================================
class TestPutMetric:
    def test_publishes_to_the_project_namespace(self, monkeypatch):
        """The namespace is a constant because the extractor's IAM policy scopes
        PutMetricData with a `cloudwatch:namespace` condition — an override would silently
        lose permission to publish."""
        seen = {}

        class Fake:
            def put_metric_data(self, **kwargs):
                seen.update(kwargs)

        monkeypatch.setattr(metrics.boto3, "client", lambda *_a, **_k: Fake())

        assert metrics.put_metric("SomeMetric") is True
        assert seen["Namespace"] == metrics.NAMESPACE

    def test_dimensions_are_stringified(self, monkeypatch):
        """CloudWatch rejects a non-string dimension value, and callers pass ints."""
        seen = {}

        class Fake:
            def put_metric_data(self, **kwargs):
                seen.update(kwargs)

        monkeypatch.setattr(metrics.boto3, "client", lambda *_a, **_k: Fake())
        metrics.put_metric("SomeMetric", dimensions={"StatusCode": 429})

        assert seen["MetricData"][0]["Dimensions"] == [{"Name": "StatusCode", "Value": "429"}]

    def test_no_dimensions_key_when_none_given(self, monkeypatch):
        """The dimensionless series is the one an alarm can watch with a plain threshold; an
        empty Dimensions list would make it a different series."""
        seen = {}

        class Fake:
            def put_metric_data(self, **kwargs):
                seen.update(kwargs)

        monkeypatch.setattr(metrics.boto3, "client", lambda *_a, **_k: Fake())
        metrics.put_metric("SomeMetric")

        assert "Dimensions" not in seen["MetricData"][0]

    def test_a_publish_failure_is_swallowed(self, monkeypatch):
        """THE contract of this module. A throttled PutMetricData, a missing IAM grant or an
        expired credential must not turn a successful scrape into a failed run."""

        class Fake:
            def put_metric_data(self, **kwargs):
                raise ClientError({"Error": {"Code": "Throttling"}}, "PutMetricData")

        monkeypatch.setattr(metrics.boto3, "client", lambda *_a, **_k: Fake())

        assert metrics.put_metric("SomeMetric") is False

    def test_even_a_credential_error_at_client_construction_is_swallowed(self, monkeypatch):
        """The client is built inside the try for exactly this reason — a NoCredentialsError
        raised while constructing it would otherwise escape."""

        def boom(*_a, **_k):
            raise RuntimeError("no credentials")

        monkeypatch.setattr(metrics.boto3, "client", boom)

        assert metrics.put_metric("SomeMetric") is False


class TestRecordScraperStatus:
    """PR-026's two-metric split: one dimensioned series for the dashboard, one
    dimensionless series an alarm can actually target."""

    @pytest.fixture
    def published(self, monkeypatch):
        calls = []

        class Fake:
            def put_metric_data(self, **kwargs):
                calls.append(kwargs)

        monkeypatch.setattr(metrics.boto3, "client", lambda *_a, **_k: Fake())
        return calls

    def test_a_200_publishes_only_the_status_metric(self, published):
        metrics.record_scraper_status(200)

        names = [c["MetricData"][0]["MetricName"] for c in published]
        assert names == [metrics.METRIC_HTTP_STATUS]

    @pytest.mark.parametrize("status", [401, 402, 429, 500])
    def test_a_failure_also_publishes_the_alarmable_series(self, published, status):
        """A CloudWatch alarm watches one series with one dimension set, so
        ScraperHttpStatus alone cannot express "alarm on ANY non-200" without enumerating
        every code in advance. That is what the dimensionless companion is for."""
        metrics.record_scraper_status(status)

        names = [c["MetricData"][0]["MetricName"] for c in published]
        assert names == [metrics.METRIC_HTTP_STATUS, metrics.METRIC_HTTP_ERRORS]

    def test_the_status_code_becomes_a_dimension(self, published):
        metrics.record_scraper_status(429)

        assert published[0]["MetricData"][0]["Dimensions"] == [
            {"Name": "StatusCode", "Value": "429"}
        ]

    def test_the_error_series_carries_no_dimensions(self, published):
        metrics.record_scraper_status(402)

        assert "Dimensions" not in published[1]["MetricData"][0]


class TestRecordScraperNoResponse:
    """The other half of PR-031.1's telemetry: a request that never came back at all.

    ``record_scraper_status`` needs an HTTP status; a ReadTimeout or a dropped connection
    has none, and before this existed those failures published nothing — the scrape simply
    stopped and the dashboard stayed flat. That is the shape the 2026-08 outage had.
    """

    @pytest.fixture
    def published(self, monkeypatch):
        calls = []

        class Fake:
            def put_metric_data(self, **kwargs):
                calls.append(kwargs)

        monkeypatch.setattr(metrics.boto3, "client", lambda *_a, **_k: Fake())
        return calls

    def test_it_publishes_both_series(self, published):
        metrics.record_scraper_no_response("ReadTimeout")

        names = [c["MetricData"][0]["MetricName"] for c in published]
        assert names == [metrics.METRIC_HTTP_STATUS, metrics.METRIC_HTTP_ERRORS]

    def test_the_status_dimension_says_noresponse_rather_than_a_number(self, published):
        """It shares ScraperHttpStatus with the real status codes on purpose, so one widget
        shows every outcome — but as a named value, because there is no code to report."""
        metrics.record_scraper_no_response("ConnectionError")

        assert published[0]["MetricData"][0]["Dimensions"] == [
            {"Name": "StatusCode", "Value": metrics.STATUS_NO_RESPONSE}
        ]

    def test_the_reason_is_logged_but_never_becomes_a_dimension(self, published, caplog):
        """Every distinct dimension value is a separate CloudWatch time series. An unbounded
        set of exception class names would fragment the exact series PR-025's alarm watches,
        so the detail goes to the log line instead."""
        with caplog.at_level(logging.WARNING):
            metrics.record_scraper_no_response("ReadTimeout")

        # Asserted on the record attribute, not on caplog.text: it travels as `extra`, which
        # is exactly where PR-018's JSON formatter picks it up and a plain formatter drops it.
        assert [r.reason for r in caplog.records] == ["ReadTimeout"]
        for call in published:
            dims = call["MetricData"][0].get("Dimensions", [])
            assert all(d["Value"] != "ReadTimeout" for d in dims)

    def test_the_error_series_carries_no_dimensions(self, published):
        metrics.record_scraper_no_response("ReadTimeout")

        assert "Dimensions" not in published[1]["MetricData"][0]
