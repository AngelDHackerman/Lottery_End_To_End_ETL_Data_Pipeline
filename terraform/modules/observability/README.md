# Module: `observability`

SNS alerts topic + optional email subscription.

**Status:** foundation landed in **PR-014** (new resources — nothing to import). Phase 4
fleshes it out: log retention (PR-023), the CloudWatch dashboard (PR-024), alarms wired
to this topic (PR-025), the scraper HTTP-status metric (PR-026), the optional S3
object-count emitter (PR-027), and the tfvars-driven email subscription docs (PR-028).

## Behavior

- `aws_sns_topic.alerts` (`loteria-alerts-<environment>`) always exists.
- `aws_sns_topic_subscription.email_alerts` is created only when `alert_email` is
  non-empty (root var `alert_email`, default `""`). **The recipient must click the
  confirmation link AWS emails** — until then the subscription is "pending confirmation"
  and no alerts are delivered.

## Inputs / outputs

- Inputs: `environment`, `alert_email` (optional).
- Outputs: `alerts_topic_arn`.

---

## Dashboard (PR-024)

`aws_cloudwatch_dashboard.loteria_pipeline` → **`loteria-pipeline-<env>`**. Output
`dashboard_url` gives a direct console link.

### ⚠️ The roadmap's Glue widgets do not exist

PR-024 asked for `glue.driver.aggregate.numCompletedTasks` and
`glue.ALL.s3.filesystem.read_bytes`. Both are **Spark** job metrics. The transform is a
Python Shell job, which publishes **no job telemetry at all**. Verified read-only against
the live account: the whole `AWS/Glue` namespace contains exactly one metric,
`ResourceUsage`, dimensioned `(Type=Resource, Resource=Job|JobRun|InteractiveSession,
Service=Glue, Class=None)` — an account-level service-quota gauge with **no `JobName`
dimension**. There are **no crawler metrics whatsoever**. This is the same
pythonshell-vs-`glueetl` split the PR-020 spike documented.

**What replaces them:** Step Functions *service-integration* metrics. Every pipeline stage
is an SFN integration, so `AWS/States` exposes per-stage success/failure/duration under the
`ServiceIntegrationResourceArn` dimension. Measured on the 2026-07-26 run:

| Integration | Calls/run | Avg runtime |
|---|---|---|
| `lambda:invoke` | 8 (extractor + 7 gold purge) | 1.9 s |
| `glue:startJobRun.sync` | 1 | 57.3 s |
| `aws-sdk:glue:startCrawler` | 2 | 5.9 s |
| `athena:startQueryExecution.sync` | 7 (gold CTAS) | 59.0 s |

Two traps in that dimension, both found the hard way:

1. **The value is account-qualified** — `arn:aws:states:us-east-1:<acct>:glue:startJobRun.sync`,
   *not* the bare `arn:aws:states:::glue:startJobRun.sync` the state machine definition
   uses. Querying the bare form returns zero datapoints with no error.
2. **It identifies the integration TYPE, not the resource.** `lambda:invoke` aggregates the
   extractor *and* all 7 gold-purge calls; per-function detail comes from the `AWS/Lambda`
   widgets.

### Layout

| Row | Widgets |
|---|---|
| header | What the pipeline is, its weekly cadence, how to read gaps |
| 1 | SFN run outcomes · execution duration (p50/p90/p99/max) · 28-day single-value summary |
| 2 | Per-stage failures · per-stage duration (both via service integrations) |
| 3 | Extractor Lambda outcomes · extractor duration · gold-purge Lambda |
| 4 | Athena bytes scanned · query timing · query outcomes (count) |
| 5 | Glue structured log lines · Glue errors & tracebacks (Logs Insights) |

### Notes on specific widgets

- **Default window is 28 days** (`start = "-P28D"`), because the pipeline runs weekly and
  the console's default 3-hour window would show an empty dashboard almost always.
- **Athena has no query-count metric.** `SampleCount` on `TotalExecutionTime` *is* the count
  of queries that reported it, which makes SUCCEEDED-vs-FAILED countable per `QueryType`.
- **Bytes scanned is the cost widget.** Athena bills per byte, and the gold CTAS re-reads all
  of silver every run — this is the line to watch if the bill moves.
- **The log widgets are the only Glue-side signal**, given the metric gap above. They rely on
  PR-018's structured JSON: `correlation_id` (= the SFN execution name) is a first-class
  queryable field. Verified live — Logs Insights auto-parses the JSON even though Glue
  prefixes each line with a tab.
- **S3 object counts per medallion layer are absent** — that needs a custom metric emitter,
  which the roadmap scopes to the optional PR-027.

### Inputs added

`aws_region`, `state_machine_arn`, `extractor_lambda_name`, `gold_purge_lambda_name`,
`athena_workgroup_name`, `glue_output_log_group_name`, `glue_error_log_group_name`.
All read-only identifiers — the dashboard creates no dependency on the observed resources'
internals.

### scrape.do response codes (PR-026)

New widget, plus a restructure of the execution-duration widgets.

`SEARCH('{Loteria/Pipeline,StatusCode} MetricName="ScraperHttpStatus"', 'Sum', 86400)` draws
one line per HTTP status the proxy has returned. `SEARCH` rather than explicit metric entries
because the set of codes is not known in advance — 200 today, 401/402/429 the day the free
tier lapses — and enumerating them guarantees the interesting one is missing. The
dimensionless `ScraperHttpErrors` is plotted alongside because it is the exact series
PR-025's `ScrapeDo_Failed` alarm watches, so the dashboard shows what the alarm sees.

Requires `metrics_namespace` to match `loteria.common.metrics.NAMESPACE`, or the widget
plots nothing. Details: `docs/runbooks/PR-026-scraper-metric.md`.

**Percentiles moved.** The duration time series was `p50/p90/p99/max` on a daily period,
which carries no information for a weekly pipeline: almost every bucket holds one execution,
and a percentile of one datapoint is that datapoint. Measured on real data — Jul 25 gave
`p50 = p90 = p99 = max = 259,808 ms`, four lines drawn on top of each other. So:

- the daily series is now a single **"Duration per run"** line
- `p50/p90/p99` moved to the **28-day single-value** widget, where all 12 runs land in one
  bucket and the numbers separate meaningfully (p50 135s / p90 248s / p99 259s)

Duration is a health signal by itself: failed runs die at the extractor in 3–4 s, successful
ones take 64–260 s, so anything under ~10 s is a failure. The step up to ~255 s is PR-022's
gold layer, which means pre-gold history is not comparable to post-gold.

---

## Alarms (PR-025)

Six metric alarms plus one EventBridge rule, all notifying `aws_sns_topic.alerts`.

> **⚠️ The topic has no subscribers until `alert_email` is set** (PR-028). Verified live on
> 2026-08-02: `list-subscriptions-by-topic` returns empty. The alarms will hold correct
> states and tell nobody. Set `alert_email` in the gitignored `terraform.tfvars` and confirm
> the email AWS sends.

| Resource | Fires when |
|---|---|
| `loteria-sfn-execution-failed-<env>` | any execution fails (the machine has no Retry/Catch, so this catches every stage) |
| `loteria-sfn-no-success-7d-<env>` | no successful run in 7 days — the dead man's switch |
| `loteria-extractor-errors-<env>` | the extractor Lambda errors |
| `loteria-glue-transform-failed-<env>` | the bronze→silver Glue job run fails |
| `loteria-crawler-start-failed-<env>` | a silver crawler cannot be **started** |
| `loteria-crawler-failed-<env>` (EventBridge) | a silver crawl started and then **failed** |
| `loteria-scrapedo-failed-<env>` | scrape.do returns a non-200 |

Alarm 1 is the only one that *detects* everything; the per-stage alarms exist for
**attribution** — they name the broken stage in the notification. One bad run sends 2–3
emails, by design.

### Three things that are not what the roadmap assumed

**The 8-day dead man's switch is 7 days, because 8 is not possible.** CloudWatch caps an
alarm's total evaluation window at 604,800 s (`period × evaluation_periods`); 8 × 86,400
exceeds it and the API rejects the alarm. No composite/expression trick gets around a cap on
the window itself. 7 also happens to fit the weekly cadence exactly: a healthy week always
contains one success, and a missed Thursday alarms at the next 00:00 UTC.

`treat_missing_data = "breaching"` is what makes it work, and the reason is subtler than the
roadmap's note. `ExecutionsSucceeded` publishes a real `0` on a day when a run *failed*, but
**no datapoint at all** on a day when nothing ran — and "nothing ran" is precisely what this
alarm is for. Both are covered.

**Alarms 4 and 5 hit the PR-024 Glue wall again.** `Job.failure` and
`glue.driver.aggregate.numFailedTasks` are Spark metrics and do not exist here. Both are
rebuilt on `AWS/States` `ServiceIntegrationsFailed` — but the two substitutes are *not*
equally good, and that is why alarm 5 is two resources:

- The Glue job is invoked with `glue:startJobRun.**sync**`, so the integration waits for the
  job run. "Integration failed" == "job failed". Exact.
- The crawlers use `aws-sdk:glue:startCrawler`, which has **no `.sync` variant**. The
  integration succeeds the moment the crawler accepts the start call. A crawl that starts and
  then fails is completely invisible — and the execution proceeds to build gold from a
  catalog missing the new partitions. Wrong numbers, green pipeline.

The second case is covered by an EventBridge rule on `Glue Crawler State Change` /
`state: Failed`, scoped by `crawlerName`. A Logs metric filter over `/aws-glue/crawlers` was
the other candidate and was **rejected**: that group is account-wide, another project already
writes to it (stream `near-real-time-crypto-silver-crawler-crypto`, verified live), metric
filters cannot be scoped to a stream, and the crawler name does not appear on individual
error lines.

**Adding the EventBridge target replaces the SNS topic's default policy.** EventBridge needs
an explicit `SNS:Publish` grant, and `aws_sns_topic_policy` overwrites whatever SNS created
with the topic — so the policy reproduces the default account-owner statement alongside the
new one. The metric alarms themselves need no grant; CloudWatch publishes to a same-account
topic under that default.

### Inputs added

`premios_crawler_name`, `sorteos_crawler_name`, `weekly_rule_name`, `no_success_alarm_days`
(default 7, validated 1–7). Outputs: `alarm_names`, `crawler_failed_rule_name`.

Details, live evidence and the verification commands: `docs/runbooks/PR-025-alarms.md`.
