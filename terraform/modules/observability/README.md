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
