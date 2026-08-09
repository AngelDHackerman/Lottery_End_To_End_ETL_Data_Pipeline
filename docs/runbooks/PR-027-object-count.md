# PR-027 — S3 object-count emitter

**Status of the roadmap prompt:** PR-027 is marked "(Optional) … Skip if the dashboard from
PR-024 already feels rich enough." Built anyway — see §1.

**Scope:** all new resources. Nothing is imported, nothing is destroyed, no existing
resource changes except the PR-024 dashboard (two widgets added).

---

## 1. Why build an "optional" PR

Every widget PR-024 put on the dashboard measures an **execution**: did the run succeed, how
long did each stage take, what did Athena scan. None of them measures the **asset**.

Those come apart in a specific and plausible way. The pipeline can go green end to end while
adding nothing: the extractor re-scrapes a page it already has, the transformer rewrites the
same partition, every stage succeeds, `AWS/States` reports a healthy run. There is no failed
execution, so PR-025's alarms stay quiet. A **flat `raw/` line beside green executions** is
the only place that shows up.

This is the same category of defect as PR-026.1 — green pipeline, wrong/absent data — which
is why it was worth the hour.

## 2. Why S3's free metrics don't work

S3 publishes `NumberOfObjects` and `BucketSizeBytes` into `AWS/S3` for free, but **per
bucket** (optionally per storage class), never per prefix. All three medallion layers live in
`lottery-partitioned-storage-prod`. The free metrics cannot separate them, so a custom
emitter is the only option.

## 3. What gets created

| Resource | Module |
|---|---|
| `aws_lambda_function.object_count` (`lottery-object-count-prod`) | observability |
| `aws_cloudwatch_log_group.object_count` | observability |
| `aws_cloudwatch_event_rule.object_count_schedule` (`rate(1 hour)`) | observability |
| `aws_cloudwatch_event_target.object_count_lambda` | observability |
| `aws_lambda_permission.allow_eventbridge_object_count` | observability |
| `aws_iam_role.object_count_lambda` | iam |
| `aws_iam_policy.object_count_lambda_policy` + 2 attachments | iam |

Source: `src/loteria/observability/object_count.py` — a single file, zipped by Terraform's
`archive_file`, exactly like the gold-purge Lambda. **It is not part of `make build`**; its
only dependency is boto3, which the runtime ships.

Metrics: `ObjectCount` and `BytesStored` in `Loteria/Pipeline`, dimension `Layer` =
`raw` | `silver` | `gold`.

## 4. Expected plan

```
Plan: 8 to add, 2 to change, 0 to destroy.
```

The two changes:

1. `module.observability.aws_cloudwatch_dashboard.loteria_pipeline` — two widgets added, the
   log row moved from `y=33` to `y=39`. Expected.
2. `module.orchestration.aws_lambda_function.gold_purge` — **expected, benign, and one-time.**
   Read on before assuming it is a mistake.

### Why gold_purge shows up in this PR's plan

It looks alarming: PR-027 does not touch the gold-purge Lambda. The diff is only
`source_code_hash` and `last_modified`, both `(known after apply)`.

The cause is a chain nobody wrote on purpose:

- PR-023 added `depends_on = [module.iam]` to `module.orchestration` (to stop the state
  machine being updated before the role that grants it log-delivery rights).
- **A module with `depends_on` on something that has pending changes cannot have its data
  sources read at plan time.** Terraform defers them to apply.
- PR-027 adds four resources to `module.iam` (the emitter's role, policy and two
  attachments), so `module.iam` has pending changes…
- …so `module.orchestration.data.archive_file.gold_purge` is deferred, so its
  `output_base64sha256` is unknown, so `aws_lambda_function.gold_purge.source_code_hash` is
  unknown, so Terraform plans an update.

Confirm it is harmless before applying — the archive is deterministic, so the hash it will
produce already matches what is deployed:

```bash
openssl dgst -sha256 -binary terraform/modules/orchestration/build/gold_purge_and_load.zip \
  | openssl base64
aws lambda get-function-configuration --function-name lottery-gold-purge-prod \
  --query 'CodeSha256' --output text
```

Recorded 2026-08-09: both `rWrVT00c7xXSus7LVe7O9XDY9/xPJIWBBbq7Yjj0+rM=`. The apply
re-uploads byte-identical code.

It is **one-time**: once `module.iam` has no pending changes, the data source reads at plan
time again and `gold_purge` goes back to a no-op. Verified by planning the same tree on
`master` (where `module.iam` is unchanged): `10 to add, 0 to change` — no `gold_purge`.

**Reusable lesson:** any future PR that adds a resource to `module.iam` will make this
Lambda appear in the plan. That is the `depends_on`, not your change.

> Do **not** run `make build` for this PR. It rebuilds the extractor's layer/package zips,
> which changes `source_code_hash` from identical sources and forces the Lambda layer to be
> replaced — unrelated churn. Same trap as PR-025 and PR-026.1.

## 5. Verification

### 5a. Before applying — the counting logic

`_count_prefix` can be exercised directly against the real bucket with no writes:

```bash
python3 -c "
import sys, boto3
sys.path.insert(0,'src/loteria/observability')
import object_count as oc
s3 = boto3.client('s3')
for p in ['raw/','silver/','gold/']:
    print(p, oc._count_prefix(s3,'lottery-partitioned-storage-prod',p))
"
```

Cross-check against the CLI:

```bash
for p in raw/ silver/ gold/; do
  echo -n "$p "
  aws s3api list-objects-v2 --bucket lottery-partitioned-storage-prod \
    --prefix "$p" --query 'length(Contents)' --output text
done
```

Recorded 2026-08-09: `raw/ 110`, `silver/ 220`, `gold/ 13` — identical from both paths.

### 5b. After applying — invoke it by hand

```bash
aws lambda invoke --function-name lottery-object-count-prod \
  --cli-binary-format raw-in-base64-out /dev/stdout | head -5
```

The handler returns its counts, so the response body *is* the smoke test. Expect
`"published": true`. **`"published": false` means the `PutMetricData` was denied** — check
that `METRICS_NAMESPACE` on the function equals the `cloudwatch:namespace` condition on
`lottery-object-count-policy-prod`. That mismatch is silent by design (the code swallows
publish errors so telemetry can't break anything), so this return value is the only easy
signal.

Confirm the datapoints landed:

```bash
aws cloudwatch list-metrics --namespace Loteria/Pipeline \
  --query 'Metrics[?MetricName==`ObjectCount`].Dimensions'
```

### 5c. Confirm the schedule actually fires

The `aws_lambda_permission` is the piece that silently breaks this — EventBridge invokes
Lambda by **resource policy**, not by execution role, so without it the rule fires forever
and nothing runs. After an hour:

```bash
aws cloudwatch get-metric-statistics --namespace AWS/Events \
  --metric-name Invocations --start-time "$(date -u -d '2 hours ago' +%FT%TZ)" \
  --end-time "$(date -u +%FT%TZ)" --period 3600 --statistics Sum \
  --dimensions Name=RuleName,Value=lottery-object-count-schedule-prod
```

`FailedInvocations > 0` on that rule is the signature of a missing permission.

### 5d. The dashboard

Row 6 of `loteria-pipeline-prod`. Both widgets use `period = 86400, stat = Maximum` — the
daily high-water mark. `Average` would smear the weekly step across the day it happened.

Expected shapes once a few days of data exist: `raw` steps up once a week, `silver` tracks
it, `gold` stays roughly flat (the CTAS drops and recreates the same 7 tables, so its count
oscillates rather than grows). **`raw` climbing while `silver` doesn't** means the
transformer is skipping work.

## 6. Cost

| Item | Monthly |
|---|---|
| 730 invocations, 128 MB, <1 s | free tier / < $0.01 |
| ~2,200 `ListObjectsV2` requests | < $0.02 |
| 6 custom metrics (3 layers × 2) | $1.80 |

Dropping `BytesStored` would halve the metric line. It is kept because it comes free from the
same API response and distinguishes "we wrote a file" from "we wrote a file with data in it"
— a truncated scrape still increments `ObjectCount`.

## 7. Turning it off

```hcl
enable_object_count_emitter = false
```

Removes the Lambda, log group, schedule and metrics. The dashboard widgets remain and render
empty, so re-enabling needs no dashboard change.

## 8. Known limits

- **O(objects) per run.** Fine at a few hundred keys per prefix. When it isn't, move to S3
  Inventory (a daily manifest) rather than raising the timeout — `ObjectCount` is a
  slow-moving number and the pipeline writes weekly.
- **No alarm on these metrics.** A "raw/ hasn't grown in 8 days" alarm is the natural
  follow-up, but it overlaps PR-025's dead-man's switch and needs a few weeks of baseline
  first. Not filed as a PR yet.
- `processed/` (the frozen legacy prefix from PR-012) is excluded.
