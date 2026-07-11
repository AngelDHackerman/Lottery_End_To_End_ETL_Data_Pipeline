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

## Wiring

The Step Function's crawler names come from `module.catalog` outputs, the lambda ARN from
`module.etl_lambda`, the job name from `module.etl_glue` — no free-floating var strings.

- Inputs: `sfn_execution_role_arn`, `eventbridge_to_sfn_role_arn`, `extractor_lambda_arn`,
  `glue_job_name`, `premios_crawler_name`, `sorteos_crawler_name`, `environment`.
- Outputs: `state_machine_arn`, `state_machine_name`, `weekly_rule_name`.

## Later

- **PR-022** extends the state machine with the Gold CTAS map state + gold crawler.
- **PR-018** passes `CORRELATION_ID` (`$$.Execution.Name`) to the Lambda + Glue job.
