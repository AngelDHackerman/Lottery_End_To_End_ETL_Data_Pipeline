# PR-025 — CloudWatch alarms

**Module:** `terraform/modules/observability` (`alarms.tf`)
**Depends on:** PR-014 (SNS topic), PR-023 (log groups referenced in alarm text), PR-024
(the dashboard the alarm descriptions link to), **PR-026** (the `ScraperHttpErrors` metric
alarm 6 watches — which is why PR-026 was executed first).

---

## ⚠️ Read this before applying: the alarms have nowhere to send anything

Verified live on 2026-08-02:

```
$ aws sns list-subscriptions-by-topic --topic-arn arn:aws:sns:us-east-1:913524903233:loteria-alerts-prod
(empty)
```

`alert_email` defaults to `""`, so PR-014 created the topic with **no subscription**. Every
alarm below will publish into a topic with zero subscribers — the alarm state will be
correct in the console and **no one will be told**. Wiring the email is PR-028, which the
roadmap puts last in Phase 4.

**You do not need PR-028 to fix this.** PR-028 only adds a placeholder to the public
`terraform.tfvars.example` and writes the docs. What actually creates the subscription is
`alert_email` in the gitignored `terraform/terraform.tfvars`:

```hcl
alert_email = "you@example.com"   # the owner's real address — tfvars is gitignored
```

Setting it adds one resource to the plan (`aws_sns_topic_subscription.email_alerts`).

then **click the confirmation link AWS emails** — Terraform cannot confirm it for you, and
until you do, the subscription reads `PendingConfirmation` and delivers nothing.

---

## What the roadmap asked for vs. what exists

| # | Roadmap | Built | Why it changed |
|---|---|---|---|
| 1 | `SFN ExecutionsFailed > 0` / 5 min | `loteria-sfn-execution-failed-prod` | as specified |
| 2 | `ExecutionsSucceeded < 1` over **8 days** | `loteria-sfn-no-success-7d-prod` (**7** days) | CloudWatch hard-caps the evaluation window at 604,800 s |
| 3 | `Lambda Errors > 0` / 5 min | `loteria-extractor-errors-prod` | as specified |
| 4 | `AWS/Glue Job.failure > 0` | `loteria-glue-transform-failed-prod` (`AWS/States`) | the metric does not exist |
| 5 | `AWS/Glue glue.driver.aggregate.numFailedTasks > 0` | `loteria-crawler-start-failed-prod` **+** EventBridge rule `loteria-crawler-failed-prod` | the metric does not exist, and one substitute is not enough |
| 6 | `ScraperHttpStatus` non-200 | `loteria-scrapedo-failed-prod` (on `ScraperHttpErrors`) | an alarm watches one series; see PR-026 |

`terraform plan`: **9 to add, 0 to change, 0 to destroy** — 6 metric alarms, the EventBridge
rule + target, and the SNS topic policy. No churn on anything that already exists.

---

## 1. The 8-day alarm is not buildable. 7 is the maximum.

From the [PutMetricAlarm reference](https://docs.aws.amazon.com/AmazonCloudWatch/latest/APIReference/API_PutMetricAlarm.html):

> An alarm's total current evaluation period can be no longer than **seven days**, so
> `Period` multiplied by `EvaluationPeriods` can't be more than **604,800 seconds**. For
> alarms with a period of less than one hour (3,600 seconds), the total evaluation period
> can't be longer than one day (86,400 seconds).

8 days × 86,400 s = 691,200 s. The API rejects it. This is not something a composite alarm
or a metric-math expression routes around — the cap is on the alarm's evaluation window
itself, not on how the value is computed. `7 × 86,400 = 604,800` is the exact ceiling, and
that is what the module uses (`no_success_alarm_days`, validated to 1–7).

**7 is also the better number for this pipeline.** The trigger is weekly (Thursday 18:00
UTC). In any 7 consecutive UTC-day buckets a healthy pipeline has exactly one success, so
all-7-breaching never happens by accident. A missed Thursday leaves 7 empty buckets and the
alarm fires at the next **00:00 UTC**, about 6 hours after the run should have finished. The
8-day target would only have delayed that by a day.

### The missing-data behavior, corrected

The roadmap note says `ExecutionsSucceeded` "reports no datapoints rather than zero when
nothing runs". That is half right, and the live data shows both halves:

```
2026-07-30T00:00Z  1.0   <- Thursday, succeeded
2026-07-25T00:00Z  1.0
2026-07-23T00:00Z  0.0   <- an execution RAN and FAILED: a real 0 datapoint
2026-07-21T00:00Z  0.0
2026-07-20T00:00Z  0.0
(2026-07-26 .. 2026-07-29: no datapoint at all — nothing ran)
```

- Day with a **failed** run → `Sum = 0` (a real datapoint).
- Day with **no** run → no datapoint at all.

`treat_missing_data = "breaching"` plus `threshold = 1 / LessThanThreshold` covers both:
`0 < 1` breaches, and missing is forced to breaching. Under the default `"missing"` setting
the second case — the pipeline silently not running, the exact thing this alarm exists for —
would produce nothing to evaluate and the alarm could never fire.

---

## 2. Alarms 4 and 5: the Glue metrics still do not exist

Same dead end PR-020 and PR-024 hit. `AWS/Glue` holds exactly one metric in this account
(`ResourceUsage`, an account-level service-quota gauge with no `JobName` dimension). There
are no crawler metrics at all. The transform is a **Python Shell** job; `Job.failure` and
`glue.driver.aggregate.*` are **Spark** metrics.

The substitute is `AWS/States` `ServiceIntegrationsFailed`, dimensioned by
`ServiceIntegrationResourceArn`. All four values confirmed present live:

```
arn:aws:states:us-east-1:913524903233:lambda:invoke
arn:aws:states:us-east-1:913524903233:glue:startJobRun.sync
arn:aws:states:us-east-1:913524903233:aws-sdk:glue:startCrawler
arn:aws:states:us-east-1:913524903233:athena:startQueryExecution.sync
```

Note these are **account-qualified** — the bare `arn:aws:states:::glue:...` form used in the
state machine definition matches zero datapoints, silently (PR-024's trap 1).

### The Glue job substitute is exact; the crawler substitute is not

This asymmetry is the whole reason alarm 5 became two resources:

| Stage | Integration | Waits for completion? | So a failed integration means |
|---|---|---|---|
| Glue transform | `glue:startJobRun.**sync**` | yes | the **job run failed** — exact |
| Silver crawlers | `aws-sdk:glue:startCrawler` | **no** | only that the crawler could not be **started** |

There is no `.sync` variant of `startCrawler`. The state machine fires it and moves on, so a
crawl that starts and then fails is invisible: the integration succeeded, Glue publishes no
crawler metric, and the execution goes on to build gold. Silver's new partitions never get
registered, the gold CTAS reads a stale catalog, and you get **wrong numbers with a green
pipeline**. That is worth an alarm.

### Why the crawler signal is an EventBridge rule, not a metric filter

The obvious alternative — a `aws_cloudwatch_log_metric_filter` over `/aws-glue/crawlers`
counting `ERROR` lines — was rejected on evidence:

- That log group is **account-wide** (PR-023 §3) and another project already writes to it.
  Verified live, its streams include `near-real-time-crypto-silver-crawler-crypto`.
- Metric filters apply to **every stream in a group** and cannot be scoped to a stream.
- The crawler name is not on individual log lines. The format is
  `[<crawl-id>] LEVEL : message` — the name appears only in the stream name and the opening
  `BENCHMARK : Running Start Crawl for Crawler <name>` line.

So the filter would have alarmed on an unrelated project's crawler failures. The EventBridge
rule is scoped by `crawlerName` and carries the failure message into the notification:

```json
{"source":["aws.glue"],
 "detail-type":["Glue Crawler State Change"],
 "detail":{"state":["Failed"],
           "crawlerName":["lottery-premios-silver-crawler","lottery-sorteos-silver-crawler"]}}
```

States are `Started` / `Succeeded` / `Failed`, capitalized (Glue developer guide). An
`input_transformer` renders the email as
`Glue crawler <name> FAILED at <time>: <message>` instead of a wall of JSON.

**Out of scope, and worse than it first looked → filed as PR-026.5.** Because `startCrawler`
does not wait, the gold CTAS does not merely start when a crawl *fails* — it races every
crawl, including the successful ones. Measured on the 2026-07-30 run: the first two `RunCTAS`
began at 15:02:02, and the sorteos crawler only finished writing to the catalog at 15:02:55
— **53 seconds later**. Since the silver tables are partitioned by `(year, sorteo)`, every
weekly run creates a new partition that Athena cannot see until the crawler registers it.

**None of the alarms in this PR catch that**, and that is the point worth remembering: they
fire when a crawl *fails*, but here every crawl succeeds. The pipeline reports green while a
non-deterministic subset of gold tables (whichever two lose the `Map` scheduling race) is
built from last week's catalog. See PR-026.5 in `roadmap.md` for the full timeline and the
proposed `Wait` + `GetCrawler` poll.

---

## 3. The SNS topic policy replaces the default — deliberately

EventBridge cannot publish to SNS without an explicit resource-policy grant, and attaching
`aws_sns_topic_policy` **overwrites** whatever SNS generated at topic creation. The policy
therefore has two statements:

1. `DefaultStatement` — a faithful reproduction of the SNS default (all topic actions,
   `Principal: *`, gated by `AWS:SourceOwner = <account>`). Dropping it would silently break
   console/CLI access and subscription management on the topic.
2. `AllowEventBridgePublish` — `SNS:Publish` for `events.amazonaws.com`, conditioned on
   `aws:SourceArn` = this rule's ARN, so the grant does not extend to every rule in the
   account.

The six **metric alarms need no grant**: CloudWatch publishes to a same-account topic under
the default statement.

---

## 4. Expected alarm states right after apply

| Alarm | Expected initial state | Why |
|---|---|---|
| `loteria-sfn-execution-failed-prod` | OK | `notBreaching`, no failures in the window |
| `loteria-sfn-no-success-7d-prod` | OK | last success 2026-07-30, inside 7 days |
| `loteria-extractor-errors-prod` | OK | `notBreaching` |
| `loteria-glue-transform-failed-prod` | OK | `notBreaching` |
| `loteria-crawler-start-failed-prod` | OK | `notBreaching` |
| `loteria-scrapedo-failed-prod` | **INSUFFICIENT_DATA or OK** | see below |

`ScraperHttpErrors` **has never been published**. Confirmed live — the namespace currently
holds only `ScraperHttpStatus{StatusCode=200}`, because every run since PR-026 landed has
succeeded. An alarm on a metric with no history may sit in `INSUFFICIENT_DATA` rather than
`OK`. **That is not a misconfiguration**, and it resolves the first time the proxy returns a
non-200. Do not "fix" it by widening the alarm.

### Alarms are a pulse, not a state

Every 5-minute alarm here uses `treat_missing_data = "notBreaching"`, which means it returns
to OK five minutes after the failure. **The notification is the signal** — by the time you
open the console it will read OK. This is correct for a pipeline that runs weekly (the
alternative, `"missing"`, parks every alarm in `INSUFFICIENT_DATA` permanently and makes the
state meaningless). `ok_actions` is deliberately unset everywhere: it would send a "recovered"
email five minutes after every failure email, which carries no information.

The dead-man's-switch alarm is the exception — it stays in ALARM until a run actually
succeeds.

---

## 5. Verification

**Step 1 — plan** (no AWS mutation).

```bash
cd terraform
terraform plan                # expect: 9 to add, 0 to change, 0 to destroy
```

If `alert_email` is set for the first time, the plan is **10 to add** — the extra resource
is `aws_sns_topic_subscription.email_alerts`.

⚠️ **Do NOT run `make build` for this PR.** Two traps, both hit while writing this runbook:

1. **The Makefile lives at the repo root, not in `terraform/`.** `cd terraform && make build`
   fails with "No rule to make target".
2. **More importantly, rebuilding pollutes the plan.** PR-025 touches no Python code, but
   `build_lambda_layer.sh` re-runs `pip` and rezips, producing a different `source_code_hash`
   even from identical sources. That forces `aws_lambda_layer_version.loteria_deps` to be
   **replaced** (layer version N → N+1) and drags the two Lambda functions plus the S3 object
   along with it. Measured: the plan went from `10 to add, 0 change, 0 destroy` to
   `11 to add, 3 to change, 1 to destroy` — and the extra churn had nothing to do with alarms.

`make build` is needed when the Lambda/Glue **code** changed. It is not needed here, as long
as the zips already on disk are the deployed ones. If a plan shows unexpected Lambda churn,
restore the deployed artifacts instead of rebuilding:

```bash
aws s3 cp s3://lambda-code-zip-prod/lambda_layer.zip   terraform/lambda_layer.zip
aws s3 cp s3://lambda-code-zip-prod/lambda_package.zip terraform/lambda_package.zip
```

The zips must exist on disk either way — `filemd5`/`filebase64sha256` read them at **plan**
time, so a missing file fails the plan itself, not the apply.

**Step 2 — apply.** Nothing below works before this; the alarms do not exist yet.

```bash
terraform apply
```

Then confirm the SNS email AWS sends, or every check below passes while no notification
ever arrives.

**Step 3 — verify** what the apply created:

```bash
# All six alarms exist and their states are as tabulated above.
terraform output -json | jq -r '.alarm_names.value[]' \
  | xargs -I{} aws cloudwatch describe-alarms --alarm-names {} \
      --query 'MetricAlarms[].[AlarmName,StateValue]' --output text

# The crawler rule is ENABLED and targets the topic.
aws events describe-rule --name loteria-crawler-failed-prod --query '[Name,State]' --output text
aws events list-targets-by-rule --rule loteria-crawler-failed-prod --query 'Targets[].Arn' --output text

# The topic policy kept BOTH statements.
aws sns get-topic-attributes --topic-arn arn:aws:sns:us-east-1:913524903233:loteria-alerts-prod \
  --query 'Attributes.Policy' --output text | jq -r '.Statement[].Sid'
# expect: DefaultStatement / AllowEventBridgePublish
```

**Step 4 — end-to-end test of the notification path** (needs a confirmed subscription — see
the top of this runbook). `set-alarm-state` forces a transition and fires the action without
touching any metric data; the state reverts at the next real evaluation:

```bash
aws cloudwatch set-alarm-state \
  --alarm-name loteria-scrapedo-failed-prod \
  --state-value ALARM \
  --state-reason "PR-025 notification path test"
```

An email should arrive within a minute. If it does not, the subscription is unconfirmed —
check `aws sns list-subscriptions-by-topic` for `PendingConfirmation`.

Testing the crawler rule the same way means actually failing a crawl; `aws events
test-event-pattern` at least proves the pattern matches a representative event:

```bash
aws events test-event-pattern \
  --event-pattern "$(aws events describe-rule --name loteria-crawler-failed-prod --query EventPattern --output text)" \
  --event '{"id":"1","account":"913524903233","region":"us-east-1","source":"aws.glue","time":"2026-08-02T00:00:00Z","detail-type":"Glue Crawler State Change","resources":[],"detail":{"crawlerName":"lottery-premios-silver-crawler","state":"Failed","message":"test"}}'
# expect: true
```
