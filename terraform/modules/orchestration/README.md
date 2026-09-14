# Module: `orchestration`

Step Functions state machine + the **single** weekly EventBridge trigger.

**Status:** migrated in **PR-012** from `terraform-lottery/Prod/{state_machine.tf,
eventbridge.tf}` via cross-state `terraform state rm` (legacy) + `terraform import`
(main). See `docs/runbooks/PR-012-catalog-orchestration-migration.md`.

## The duplicate-trigger decision (PR-012)

The legacy stack had **two** EventBridge rules starting the same state machine:

| Rule | Schedule | Fate |
|---|---|---|
| `lottery-etl-weekly-trigger-prod` (`weekly_etl_trigger`) | `cron(0 18 ? * MON *)` — Mon 12:00 Guatemala | **KEPT** (moved here) |
| `weekly-etl-lottery-trigger-prod` (`weekly_trigger`) | `cron(0 14 ? * 6 *)` — Sat 08:00 Guatemala | **DESTROYED** |

Kept the Monday rule because it matches the documented weekly cadence (the site publishes
after the weekend draws) and its name/description were the intentional, newer pair. Two
rules meant the pipeline ran twice a week for no reason. The Saturday rule + its target are
destroyed via the legacy stack (the one deliberate destroy in this whole migration).

> **Schedule changed to Thursday (post-PR-012).** The kept rule now fires
> `cron(0 18 ? * THU *)` — Thu 12:00 Guatemala — not Monday. The Saturday draws (the
> extraordinario in particular) keep loteria.org.gt behind a Cloudflare Waiting Room for
> days, and a Monday scrape lands in that window: the proxy returns HTTP 200 with the
> queue page, and the extractor fails at the sorteo-link selector. Thursday is the calm
> point of the week, so the scrape is far likelier to reach the real page. The site still
> exposes only the latest sorteo mid-week, so nothing is skipped. This lowers the odds of
> a Cloudflare hit; it does not remove the single-run-per-week SPOF (see PR-026/PR-031).

## Wiring

The Step Function's crawler names come from `module.catalog` outputs, the lambda ARN from
`module.etl_lambda`, the job name from `module.etl_glue` — no free-floating var strings.

- Inputs: `sfn_execution_role_arn`, `eventbridge_to_sfn_role_arn`, `extractor_lambda_arn`,
  `glue_job_name`, `premios_crawler_name`, `sorteos_crawler_name`, `environment`.
- Outputs: `state_machine_arn`, `state_machine_name`, `weekly_rule_name`.

## Later

- **PR-022** extends the state machine with the Gold CTAS map state + gold crawler.
- **PR-018** passes `CORRELATION_ID` (`$$.Execution.Name`) to the Lambda + Glue job.

## Log retention + Step Functions logging (PR-023)

Two log groups are now owned here:

- `/aws/lambda/lottery-gold-purge-<env>` — the PR-022 purge Lambda's group. Already exists
  in prod, so it is `terraform import`ed.
- `/aws/vendedlogs/states/lottery-etl-pipeline-<env>` — **new**. Step Functions writes
  execution logs only when a `logging_configuration` is attached, and it never had one, so
  the pipeline had no CloudWatch record of a run at all — only the console's 90-day
  execution list. The `/aws/vendedlogs/` prefix is mandatory: Terraform accepts any name,
  the service rejects anything else when creating the delivery.

Logging defaults to `level = ALL` with execution data because the pipeline runs once a week
with ~15 transitions — a few KB/week against real debugging value. Set `sfn_log_level =
"OFF"` to skip both the group and the configuration.

The state machine role needs `logs:CreateLogDelivery` & friends on `Resource = "*"` — AWS
documents those actions as not supporting resource-level permissions, so that wildcard is a
service constraint, not an oversight. Details: `docs/runbooks/PR-023-log-retention.md`.

Extra inputs: `log_retention_days` (default 30), `sfn_log_level`,
`sfn_include_execution_data`. Extra outputs: `gold_purge_log_group_name`,
`state_machine_log_group_name`.

## Waiting for the silver crawlers (PR-026.1)

**The defect this closes.** The state machine used to start the two silver crawlers with
two back-to-back `arn:aws:states:::aws-sdk:glue:startCrawler` tasks and go straight to
`PrepGold` → `BuildGold`. **There is no `.sync` variant of that integration**, so each task
completed when the API call was *accepted*, not when the crawl finished. The 7 gold CTAS
therefore raced the crawlers.

Measured on the 2026-07-30 run:

| Time (UTC-3) | Event |
|---|---|
| 15:01:48.9 | `RunSorteosCrawler` returns, SFN moves on |
| **15:02:02.2** | **first 2 of 7 `RunCTAS` start** |
| **15:02:55** | crawler logs "Finished writing to Catalog" — 53 s too late |
| 15:02:57 → 15:04:03 | the remaining 5 CTAS start, correctly |
| 15:06:34 | crawler reaches `READY` (3m39s of teardown *after* the catalog write) |

This bites because silver is partitioned by **`(year, sorteo)`** — every weekly run creates
a **brand-new partition**, which Athena cannot see until a crawler registers it. That is not
the ordinary "new files inside a known partition" case Athena resolves by itself. Which two
CTAS lose the race depends on `Map` scheduling (`MaxConcurrency = 3`), so the stale table was
**non-deterministic**, and the failure is **silent**: no error, no alarm, just a gold table
missing the newest draw.

**The fix.** `RunSilverCrawlers`, a `Parallel` state with one branch per crawler:

```
Baseline<X>Crawler   getCrawler  -> $.baseline      (which crawl was last BEFORE ours)
Start<X>Crawler      startCrawler, ResultPath null  (keep the baseline)
Init<X>Poll          attempts = 0
Wait<X>Crawler       <- loop -----------------+
Get<X>Crawler        getCrawler -> $.current  |
Check<X>Crawler      Choice ------------------+  (not done: Increment<X>Poll)
Verify<X>Crawl       Choice on LastCrawl.Status
<X>CrawlSucceeded | <X>CrawlTimedOut | <X>CrawlFailed
```

Four things are load-bearing:

- **The baseline.** `READY` is *also* the state a crawler sits in between `StartCrawler`
  returning and the control plane flipping it to `RUNNING`. Polling for `READY` alone could
  read that stale value and declare a crawl finished before it began — the same class of bug
  in a new costume. `LastCrawl.MessagePrefix` is the crawl's own UUID, so a **changed**
  prefix is positive proof a new crawl ran to completion. The fresh-account case (a crawler
  with no `LastCrawl` at all) gets its own Choice rule, and every comparison is guarded by
  `IsPresent` first.
- **`Verify<X>Crawl`.** "Finished" is not "succeeded". A FAILED crawl leaves the catalog
  exactly as stale as no crawl, so proceeding would reintroduce the defect through the back
  door. A non-`SUCCEEDED` `LastCrawl.Status` now fails the execution — which also gives the
  run an owner, PR-025's `SFN_ExecutionFailed` alarm. Note this *changes* behaviour: a failed
  crawl used to let the pipeline finish green.
- **`Parallel`, not sequential.** Both crawlers must finish before gold can build, and
  `READY` lags the catalog write by ~3.5 min of teardown. Waiting for them one after the
  other would have added that twice for nothing.
- **The budget guard.** `Check` fails the execution with `CrawlerPollTimeout` once
  `$.poll.attempts` reaches `crawler_poll_max_attempts`, so a hung crawler cannot loop
  forever. Default 30 × 30 s = 15 min against an observed worst case of 4m26s.

`Parameters = {}` starts each branch from a tiny object rather than the Glue job's response,
and `ResultPath = null` discards the branch outputs — so `PrepGold` receives exactly what it
did before and the payload stays far from the 256 KB state limit.

**No IAM change.** PR-009 already granted `glue:GetCrawler` alongside `glue:StartCrawler`,
narrowed to the two silver crawler ARNs — verified against the live `sfn-lottery-policy-prod`
v7, not just the code. The roadmap predicted this PR would need a policy edit; it does not.

**Cost.** Polling adds ~4 state transitions per 30 s per crawler — under 100 extra
transitions a week (≈ $0.002), plus up to 60 `GetCrawler` calls, which have a narrow
throttling retry on them.

Extra inputs: `crawler_poll_interval_seconds` (default 30),
`crawler_poll_max_attempts` (default 30). Runbook: `docs/runbooks/PR-026.1-crawler-race.md`.

## PR-033: the Silver data-quality gate

Three states between `RunSilverCrawlers` and `PrepGold`:

```
RunSilverCrawlers → RunSilverDQ ──pass──→ PrepGold → BuildGold
                         │
                    any error
                         ↓
                  NotifyDQFailure (SNS) → SilverDQFailed (Fail)
```

`RunSilverDQ` uses `glue:startJobRun.sync`. Unlike `startCrawler` — whose missing `.sync`
integration is the entire reason `local.crawler_branches` exists — this really does wait for
the job and fails when it fails, so no polling loop is needed.

**Why the gate is here and not earlier.** The DQ job reads Parquet straight from S3 with
boto3, so it does not technically need the catalog. Running it *after* the crawlers means a
green verdict describes the exact state Gold is about to read, and it inherits PR-026.1's
guarantee that the crawl finished — so "DQ passed but Gold missed the newest sorteo" cannot
happen.

**Why it matters more than the usual "don't publish bad numbers".** `aws_lambda_function
.gold_purge` drops each gold table and empties its S3 prefix *before* the CTAS writes it. So
admitting bad Silver would not merely produce wrong Gold — it would destroy the last
known-good Gold on the way there. The gate protects the existing data as much as the new.

**No `Retry` on `RunSilverDQ`, deliberately.** Every other Task here retries, so the absence
is a decision: a failed expectation is deterministic — the same immutable Silver validated
twice gives the same verdict — so a retry would spend a second Glue run reaching the
identical conclusion and delay the alert by a full job duration.

**`NotifyDQFailure` exists for detail, not for visibility.** PR-025's `sfn_execution_failed`
alarm already fires on any failed execution; its message is "an execution failed". This one
carries Glue's `ErrorMessage`, which `loteria.dq.glue_entrypoint` builds from
`summarize_failures()` — the suite, the expectation and the column.

⚠️ **`alerts_topic_arn` arrives as a constructed string, not as `module.observability`'s
output.** Observability already consumes this module (dashboard and alarms name the state
machine, the gold-purge Lambda and the weekly rule), so taking its output here is a module
cycle. The ARN is built by name in `terraform/main.tf`. **A rename of the topic will not show
up in a plan** — both sides stay valid strings and the failure is an `AccessDenied` at the
first DQ failure.

### The gate is itself gated

`enable_silver_dq = false` renders the definition **byte-identically** to its pre-PR-033
form: `local.dq_states` is an empty map and `local.after_crawlers` sends the crawlers
straight to `PrepGold`. That makes the stack deployable before the DQ artifacts exist, and
makes the rollback a variable flip rather than a revert.

⚠️ The three states are gated as a **JSON string** that is then `jsondecode`d, not as
`var.enable_silver_dq ? {...} : {}`. Terraform needs both branches of a conditional to unify
to one type, and an ASL state map is heterogeneous by construction — a `Task` has
`Resource`/`Parameters`/`Catch`, a `Fail` has `Error`/`Cause`, and they share no attributes.
The direct form fails with *"the 'true' value includes object attribute "SilverDQFailed",
which is absent in the 'false' value"*. Gating a string sidesteps the unification; `merge()`
then folds the decoded map into the rest of the machine.

Extra inputs: `enable_silver_dq`, `dq_glue_job_name`, `dq_log_group_name`,
`alerts_topic_arn`. The flag must match `module.etl_glue`'s — a gate pointing at a job that
was not created would fail at run time, which is why both come from one root variable.
