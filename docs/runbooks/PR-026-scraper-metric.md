# PR-026 — Scraper response-code custom metric

**Phase 4.** The weekly scrape goes through **scrape.do**, a third-party proxy on its FREE
tier. When that plan lapses or its quota runs out the proxy answers 401 / 402 / 429 — and
today that surfaces only as a generic "Lambda error", indistinguishable from a parser bug or
an S3 permission problem. This PR publishes the proxy's HTTP status as a CloudWatch metric so
PR-025's alarm can name the actual cause.

Unlike PR-023 there is nothing to import. There **is** a manual verification step, because
the metric does not exist in CloudWatch until the extractor actually runs.

---

## 1. What changed

| File | Change |
|---|---|
| `src/loteria/common/metrics.py` | **New.** `put_metric()` + `record_scraper_status()`. |
| `src/loteria/extractor/scraping.py` | Calls `record_scraper_status(resp.status_code)` in `fetch_via_proxy`, **before** the non-200 raise. |
| `terraform/modules/iam/main.tf` | `cloudwatch:PutMetricData` on the extractor role, scoped by namespace condition. |
| `terraform/modules/observability/dashboard.tf` | New "scrape.do response codes" widget; execution-duration percentiles restructured. |
| root `variables.tf` / `main.tf` | New `metrics_namespace` var threaded to the `iam` + `observability` modules. |

## 2. Two metrics, and why it isn't one

| Metric | Dimensions | Emitted | Purpose |
|---|---|---|---|
| `ScraperHttpStatus` | `StatusCode=<code>` | every request | dashboard breakdown, one line per code |
| `ScraperHttpErrors` | **none** | non-200 only | the single series PR-025's alarm watches |

A CloudWatch alarm watches exactly **one** metric with **one** dimension set. So
`ScraperHttpStatus` alone cannot express *"alarm on any non-200"* — you would have to
enumerate every code you might ever receive, in advance, and the interesting one is
guaranteed to be the one you forgot. The dimensionless `ScraperHttpErrors` gives PR-025 a
plain `>= 1` threshold on a single series.

The dashboard widget uses `SEARCH()` rather than explicit metric entries for the same reason
from the other direction: it discovers each `StatusCode` value at render time, so a
brand-new failure code appears on the graph with no Terraform change.

## 3. Telemetry must never break the pipeline

Everything in `metrics.py` swallows its own exceptions. A throttled `PutMetricData`, a
missing IAM grant or an expired credential must not turn a successful scrape into a failed
run — the observer cannot be allowed to break the observed. The `except Exception` is
deliberately broad and is commented as such.

Verified locally with a stubbed boto3 client (no AWS calls):

- publishes to `Loteria/Pipeline` with the expected `MetricData` shape
- returns `False` and raises nothing when the client throws
- HTTP 200 → 1 datapoint; HTTP 402 → 2 (status + the dimensionless error series)

Real unit tests land in Phase 5 (PR-029/PR-030 build the `tests/` harness); this PR predates
the pytest skeleton, so the check above was a throwaway script rather than a committed test.

## 4. The IAM grant is scoped by condition, not by resource

`cloudwatch:PutMetricData` supports **no resource-level permissions**, so `Resource` must be
`"*"`. It does support the `cloudwatch:namespace` condition key, which is the real scope:

```hcl
statement {
  sid       = "PublishCustomMetrics"
  actions   = ["cloudwatch:PutMetricData"]
  resources = ["*"]
  condition {
    test     = "StringEquals"
    variable = "cloudwatch:namespace"
    values   = [var.metrics_namespace]
  }
}
```

The extractor can write into `Loteria/Pipeline` and nowhere else — not `AWS/*`, not another
application's metrics.

> **⚠️ `metrics_namespace` must equal `loteria.common.metrics.NAMESPACE`.** They are
> independently declared (Terraform variable vs Python constant) and a mismatch fails
> **silently**: every `PutMetricData` is denied, `metrics.py` swallows the error, the scrape
> still succeeds, and the metric simply never appears. That is why `NAMESPACE` is a constant
> rather than an env var — an env-var-overridable value could drift out of the grant.

## 5. Owner steps

### 5.1 Build + apply

The extractor's **code changed**, so the function zip must be rebuilt. Rebuild *only* that
one — a full `make build` also regenerates `lambda_layer.zip`, whose pip install is not
byte-reproducible, which adds a spurious layer-version replacement to the plan for nothing:

```bash
cd /home/hp/Loteria_Project
bash scripts/build_lambda_function.sh     # NOT `make build`
cd terraform
terraform apply
```

Expected: **0 to add, 5 to change, 0 to destroy.**

| Change | Why |
|---|---|
| `module.etl_lambda.aws_lambda_function.extractor_lambda` | new code (imports `metrics`) |
| `module.etl_lambda.aws_s3_object.lambda_package` | new zip |
| `module.iam.aws_iam_policy.lambda_custom` | the `PutMetricData` statement |
| `module.observability.aws_cloudwatch_dashboard.loteria_pipeline` | new widget + percentile move |
| `module.orchestration.aws_lambda_function.gold_purge` | **collateral, not a real change** — see below |

> **Why `gold_purge` is in a plan that doesn't touch it.** PR-023 added
> `depends_on = [module.iam]` to the orchestration module call to fix the SFN-logging
> permission race. Module-level `depends_on` applies to **data sources too**, so
> `data.archive_file.gold_purge` is deferred to apply time whenever `module.iam` has pending
> changes; its `output_base64sha256` is then unknown at plan time, which makes the function
> look changed. `archive_file` is deterministic for identical content, so the hash resolves
> to the same value and nothing about the function actually changes. Cost: plan noise on
> every future IAM change. Kept anyway — the alternative is the permission race that broke
> the first PR-023 apply. Terraform offers no way for a child module to `depends_on` an
> individual resource in a sibling module.

### 5.2 The Glue zip does NOT need re-uploading

`build_glue_package.sh` would pick up the new `common/metrics.py`, changing the zip's hash —
but the transformer never imports it, and that S3 object is not Terraform-managed. Skip it.

### 5.3 Verify — requires a live invocation

The metric does not exist until the extractor runs. `list-metrics` returning nothing before
this point is expected, not a failure.

```bash
aws lambda invoke --function-name lottery-extractor-prod \
  --payload '{}' --cli-binary-format raw-in-base64-out /tmp/extractor-out.json
cat /tmp/extractor-out.json

# The metric should appear within ~1 minute.
aws cloudwatch list-metrics --namespace Loteria/Pipeline --output table
```

Expect `ScraperHttpStatus` with `StatusCode=200`. `ScraperHttpErrors` will **not** appear on
a healthy run — it is only published on a non-200, which is the point.

Confirm a datapoint landed:

```bash
aws cloudwatch get-metric-statistics --namespace Loteria/Pipeline \
  --metric-name ScraperHttpStatus --dimensions Name=StatusCode,Value=200 \
  --start-time "$(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ)" \
  --end-time "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --period 3600 --statistics Sum
```

If the invocation succeeds but no metric appears, the namespace/grant mismatch in §4 is the
first thing to check — `metrics.py` will have logged a `Failed to publish CloudWatch metric
(ignored)` warning to `/aws/lambda/lottery-extractor-prod`:

```bash
aws logs filter-log-events --log-group-name /aws/lambda/lottery-extractor-prod \
  --filter-pattern "Failed to publish CloudWatch metric" --max-items 5
```

> **Note on invoking directly:** the extractor returns `{"status": "ok"}` and uploads to S3
> if it finds an unprocessed sorteo, or returns early if the latest sorteo is already
> processed. Either outcome still emits the metric, because the metric is recorded at the
> proxy call — before any of that logic. A direct invoke is safe: it writes at most one new
> raw file and does not touch silver or gold.

## 6. What this does NOT catch

**The Cloudflare waiting room returns HTTP 200.** The failure mode that actually killed the
2026-07-19 and 2026-07-20 runs was a queue page served with a 200 status — the extractor then
died at the sorteo-link selector. `ScraperHttpStatus` records that as a healthy 200, so this
metric will **not** alarm on it.

What it does catch is scrape.do's own failure modes: 401 (bad/expired token), 402 (free plan
lapsed / payment required), 429 (quota or rate limit), 5xx (proxy outage). Those are real and
currently invisible.

Catching the waiting room needs response-content inspection — a `<title>Waiting Room` check
in the extractor, or PR-031's scraper contract test. Not folded in here: it is a different
mechanism (content, not status code) and belongs with the canary work.
