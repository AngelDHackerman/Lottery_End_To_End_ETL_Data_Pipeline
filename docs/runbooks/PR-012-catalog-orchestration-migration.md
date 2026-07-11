# PR-012 — Migrate `catalog` + `orchestration`, kill the duplicate EventBridge rule

**Goal:** Move the Glue catalog database, the two silver crawlers, the Athena workgroup,
the Step Function, and the (kept) weekly EventBridge trigger from the **legacy** stack
into `terraform/modules/{catalog,orchestration}/` in the **main** stack — nothing
recreated — AND perform the one deliberate **destroy** of the migration: the duplicate
Saturday trigger.

> **Who runs this:** the repo owner, with prod credentials. Same cross-state pattern as
> PR-007..011 (`state rm` + `import`), **plus one legacy `apply` that destroys 2
> resources** (the duplicate rule + its target — the unwanted ones, per roadmap).

## What moves (7 imported)

| Legacy address | New address |
|---|---|
| `aws_glue_catalog_database.lottery_db` | `module.catalog.aws_glue_catalog_database.lottery_db` |
| `aws_glue_crawler.premios_silver_crawler` | `module.catalog.aws_glue_crawler.premios_silver_crawler` |
| `aws_glue_crawler.sorteos_silver_crawler` | `module.catalog.aws_glue_crawler.sorteos_silver_crawler` |
| `aws_athena_workgroup.lottery_wg` | `module.catalog.aws_athena_workgroup.lottery_wg` |
| `aws_sfn_state_machine.pipeline_state_machine` | `module.orchestration.aws_sfn_state_machine.pipeline_state_machine` |
| `aws_cloudwatch_event_rule.weekly_etl_trigger` | `module.orchestration.aws_cloudwatch_event_rule.weekly_etl_trigger` |
| `aws_cloudwatch_event_target.trigger_step_function` | `module.orchestration.aws_cloudwatch_event_target.trigger_step_function` |

## What is deleted from code but KEPT in AWS (2, `state rm` only)

- `aws_glue_crawler.premios_crawler` (`lottery-premios-crawler`) and
  `aws_glue_crawler.sorteos_crawler` (`lottery-sorteos-crawler`) — they crawl the
  `processed/` prefix the transformer no longer writes. Unmanaged after this PR; delete
  by hand whenever (`aws glue delete-crawler --name ...`). The S3 prefix `processed/`
  is **preserved**.

## What is DESTROYED in AWS (2, via legacy apply)

- `aws_cloudwatch_event_rule.weekly_trigger` (`weekly-etl-lottery-trigger-prod`,
  Sat 14:00 UTC) + `aws_cloudwatch_event_target.trigger_state_machine` — the duplicate
  trigger. The kept Monday rule covers the weekly run (see the orchestration README).

## Prerequisites

```bash
export AWS_PROFILE=angel-adming
export AWS_REGION=us-east-1
```

Merge order: PR-010 (#11) and PR-011 (#12) merged + their state ops done.

## Step 1 — Import the 7 into the MAIN stack

```bash
cd terraform

# catalog (db import id = "ACCOUNT_ID:db_name"; crawlers/workgroup = name)
terraform import module.catalog.aws_glue_catalog_database.lottery_db      913524903233:lottery_santalucia_db
terraform import module.catalog.aws_glue_crawler.premios_silver_crawler   lottery-premios-silver-crawler
terraform import module.catalog.aws_glue_crawler.sorteos_silver_crawler   lottery-sorteos-silver-crawler
terraform import module.catalog.aws_athena_workgroup.lottery_wg           lottery-wg

# orchestration (sfn = ARN; rule = "bus/name"; target = "bus/rule/target-id")
terraform import module.orchestration.aws_sfn_state_machine.pipeline_state_machine arn:aws:states:us-east-1:913524903233:stateMachine:lottery-etl-pipeline-prod
terraform import module.orchestration.aws_cloudwatch_event_rule.weekly_etl_trigger default/lottery-etl-weekly-trigger-prod
terraform import module.orchestration.aws_cloudwatch_event_target.trigger_step_function default/lottery-etl-weekly-trigger-prod/StepFunctionLotteryETL
```

If any import says "Resource already managed," skip it.

## Step 2 — Remove the 9 from the LEGACY stack

The 7 moved resources **plus** the 2 legacy `processed/` crawlers (deleted from code,
kept in AWS). Do **NOT** `state rm` the duplicate `weekly_trigger` /
`trigger_state_machine` — those stay in state so Step 3 destroys them.

```bash
cd ../terraform-lottery/Prod

terraform state rm \
  aws_glue_catalog_database.lottery_db \
  aws_glue_crawler.premios_silver_crawler \
  aws_glue_crawler.sorteos_silver_crawler \
  aws_glue_crawler.premios_crawler \
  aws_glue_crawler.sorteos_crawler \
  aws_athena_workgroup.lottery_wg \
  aws_sfn_state_machine.pipeline_state_machine \
  aws_cloudwatch_event_rule.weekly_etl_trigger \
  aws_cloudwatch_event_target.trigger_step_function
```

## Step 3 — Destroy the duplicate trigger (legacy apply)

```bash
terraform plan
```

**Expected: exactly `0 to add, 0 to change, 2 to destroy`** —
`aws_cloudwatch_event_rule.weekly_trigger` and
`aws_cloudwatch_event_target.trigger_state_machine`. Nothing else.

- ❌ If ANY other resource shows as destroy, a `state rm` was missed — STOP, do not apply.

```bash
terraform apply   # destroys only the duplicate Saturday rule + target
```

## Step 4 — Verify the MAIN plan is a no-op

```bash
cd ../../terraform && terraform plan
```

**Expected:** `No changes.` (the module reproduces the deployed definition exactly — the
Step Function already crawls the silver crawlers, confirmed back in PR-004).

- ❌ Any **create** = missed import. A `definition` diff on the state machine = the
  wiring changed a name — STOP and compare.

## Step 5 — Smoke-test

```bash
aws stepfunctions start-execution --state-machine-arn \
  arn:aws:states:us-east-1:913524903233:stateMachine:lottery-etl-pipeline-prod
```

Full run must succeed (Lambda → Glue job → both silver crawlers). Also confirm only ONE
enabled rule targets the state machine:

```bash
aws events list-rule-names-by-target --target-arn \
  arn:aws:states:us-east-1:913524903233:stateMachine:lottery-etl-pipeline-prod
```

Expected: only `lottery-etl-weekly-trigger-prod`.

## Rollback

The moves roll back like every other PR (re-import into legacy, `state rm` from main,
`git revert`). The destroyed duplicate rule can be recreated from the old config in git
history if ever wanted (it was redundant).

## What this PR touches

- **Adds:** `terraform/modules/catalog/` (db + 2 silver crawlers + Athena workgroup) and
  `terraform/modules/orchestration/` (state machine + Monday rule + target), wired in the
  root; the iam module's crawler-name inputs now come from `module.catalog` outputs.
- **Edits (legacy, code only):** `glue_crawlers.tf`, `glue_crawlers_silver.tf`,
  `state_machine.tf`, `eventbridge.tf`, `athena.tf`, `cloudwatch_event_rule.tf`,
  `cloudwatch_event_target.tf` → pointers.
- **State ops (owner):** import 7 into main; `state rm` 9 from legacy; 1 legacy apply
  destroying the 2 duplicate-trigger resources.
- **Live change:** the duplicate Saturday trigger stops existing (pipeline now runs
  once a week, Monday). Everything else is a pure move.
