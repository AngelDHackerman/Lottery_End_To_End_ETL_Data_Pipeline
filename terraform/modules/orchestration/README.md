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
