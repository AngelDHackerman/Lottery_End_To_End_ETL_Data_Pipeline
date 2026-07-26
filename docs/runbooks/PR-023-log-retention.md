# PR-023 — Log retention everywhere

**Phase 4 (Observability), step 1.** Every CloudWatch log group the pipeline writes to was
created implicitly by an AWS service with **no retention policy** — logs accumulated
forever. This PR makes the groups explicit Terraform resources with
`retention_in_days = var.log_retention_days` (default 30), and turns on Step Functions
execution logging, which was off entirely.

> **Owner action required.** Five of the six log groups **already exist** in prod, so they
> must be `terraform import`ed before the apply. A blind apply fails with
> `ResourceAlreadyExistsException`.

---

## 1. What changed

| Module | Log group | Written by | State before |
|---|---|---|---|
| `etl-lambda` | `/aws/lambda/lottery-extractor-prod` | extractor Lambda | exists, no retention → **import** |
| `orchestration` | `/aws/lambda/lottery-gold-purge-prod` | gold-purge Lambda (PR-022) | exists, no retention → **import** |
| `orchestration` | `/aws/vendedlogs/states/lottery-etl-pipeline-prod` | Step Functions | **does not exist** → created |
| `etl-glue` | `/aws-glue/python-jobs/output` | Glue Python Shell stdout | exists, no retention → **import** |
| `etl-glue` | `/aws-glue/python-jobs/error` | Glue Python Shell stderr | exists, no retention → **import** |
| `catalog` | `/aws-glue/crawlers` | both silver crawlers | exists, no retention → **import** |

Plus three in-place updates:

- `module.iam.aws_iam_policy.glue_job_policy` — the `AllowCloudWatchLogs` statement drops
  its `"*"` resource for the `/aws-glue/*` log-group namespace (resolves the `TODO PR-023`
  left in PR-009).
- `module.iam.aws_iam_policy.sfn_execution_policy` — split into two statements so Step
  Functions can actually deliver logs (see §4).
- `module.orchestration.aws_sfn_state_machine.pipeline_state_machine` —
  `logging_configuration` goes from `level = "OFF"` to `ALL` with
  `include_execution_data = true`.

### New variables (root)

| Variable | Default | Purpose |
|---|---|---|
| `log_retention_days` | `30` | Retention for every group this stack owns. `0` = never expire. Validated against the exact set CloudWatch accepts, so a bad value fails at plan time. |
| `manage_shared_glue_log_groups` | `true` | Whether to own the account-wide `/aws-glue/*` groups (see §3). |
| `sfn_log_level` | `"ALL"` | `OFF` / `ERROR` / `FATAL` / `ALL`. `OFF` skips the group *and* the `logging_configuration`. |
| `sfn_include_execution_data` | `true` | Log state input/output payloads. |

---

## 2. Why some log groups are declared *before* the resource that writes to them

Each Lambda log group is declared from a `local` name (`lottery-extractor-${var.environment}`)
rather than from `aws_lambda_function.*.function_name`, and the function carries a
`depends_on` pointing back at the group.

That ordering is deliberate. If the group referenced the function, Terraform would create
the function first — and on a fresh deploy the function's first invocation makes AWS
auto-create `/aws/lambda/<name>` with no retention, at which point Terraform's own
`aws_cloudwatch_log_group` collides with it. Group first, function second.

---

## 3. The `/aws-glue/*` groups are ACCOUNT-WIDE, not per-job

This is the non-obvious part of the PR.

Glue gives a **Python Shell** job no log group of its own. Every `pythonshell` job in the
account writes stdout to `/aws-glue/python-jobs/output` and stderr to
`/aws-glue/python-jobs/error`; every crawler writes to `/aws-glue/crawlers`. The
`--continuous-log-logGroup` argument that *would* produce a per-job group is Spark-only
(same job-family split documented in the PR-020 spike).

So the only way to put retention on Glue's logs is to let this stack own three groups that
are shared with any other Glue workload in the account. That is safe here — the transform
job is the account's only Python Shell job and the two silver crawlers are its only
crawlers — but it is a real caveat, hence the `manage_shared_glue_log_groups` escape hatch.
Set it to `false` and the three groups are left alone entirely.

**Note also:** `terraform destroy` would delete these shared groups. Glue recreates them on
the next run, so it is not destructive to the pipeline, but it does drop other jobs' history
if the account ever gains any.

### Out of scope (worth a look, manually)

`describe-log-groups` shows two more unretained groups this stack does **not** create and
does not manage:

| Group | Stored |
|---|---|
| `/aws-glue/jobs/error` | ~230 MB |
| `/aws-glue/jobs/logs-v2` | ~154 MB |

These are the *Spark* Glue namespace — leftovers from earlier, now-deleted job runs, not
written by anything in this repo. Nearly 400 MB of never-expiring logs is real (if small)
recurring storage cost. Set retention by hand if you want them gone:

```bash
aws logs put-retention-policy --log-group-name /aws-glue/jobs/error    --retention-in-days 30
aws logs put-retention-policy --log-group-name /aws-glue/jobs/logs-v2 --retention-in-days 30
```

---

## 4. Step Functions logging needs two IAM statements, and one of them must stay `"*"`

PR-009 left a `TODO PR-023: scope to the SFN log-group ARN once created explicitly`. The
group now exists, but the wildcard only half goes away — for a documented reason.

Step Functions does not write to CloudWatch directly. It provisions a **log delivery**, and
the actions that authorize that (`logs:CreateLogDelivery`, `logs:PutResourcePolicy`,
`logs:DescribeLogGroups`, …) are documented by AWS as **not supporting resource-level
permissions**. Their `Resource` must be `"*"` or logging silently fails to start. So the
policy is now:

- `AllowSfnLogDeliverySetup` — the 8 delivery actions, `Resource = "*"` **by service
  constraint**, with the reason written into the code so it does not read as an
  un-narrowed wildcard.
- `LogsForSFN` — `CreateLogStream` + `PutLogEvents`, scoped to
  `arn:aws:logs:…:log-group:/aws/vendedlogs/states/lottery-etl-pipeline-prod` and its
  `:log-stream:*`.

`CreateLogGroup` is dropped from the role: Terraform owns the group now, so the state
machine never needs to make one.

The group name must start with `/aws/vendedlogs/` — any other prefix is accepted by
Terraform and then rejected by Step Functions when it tries to create the delivery.

**Cost:** the pipeline runs once a week and the state machine has ~15 transitions per run
(7 of them the gold Map iterations), so `level = ALL` is a few KB/week. That is why the
default is `ALL` rather than `ERROR` — the debugging value dwarfs the bill.

---

## 5. Owner steps

### 5.0 Prerequisite

`make build` before any plan/apply — `filemd5`/`filebase64sha256` read the zips at plan
time (PR-019).

```bash
cd /home/hp/Loteria_Project
make build
cd terraform
terraform init -backend-config=backend.hcl
```

### 5.1 Import the five existing groups

Log-group import IDs are just the group name.

```bash
cd /home/hp/Loteria_Project/terraform

terraform import module.etl_lambda.aws_cloudwatch_log_group.extractor \
  /aws/lambda/lottery-extractor-prod

terraform import module.orchestration.aws_cloudwatch_log_group.gold_purge \
  /aws/lambda/lottery-gold-purge-prod

terraform import 'module.etl_glue.aws_cloudwatch_log_group.python_shell["/aws-glue/python-jobs/output"]' \
  /aws-glue/python-jobs/output

terraform import 'module.etl_glue.aws_cloudwatch_log_group.python_shell["/aws-glue/python-jobs/error"]' \
  /aws-glue/python-jobs/error

terraform import 'module.catalog.aws_cloudwatch_log_group.crawlers[0]' \
  /aws-glue/crawlers
```

(The quoting matters — `zsh` eats the brackets and quotes otherwise.)

`/aws/vendedlogs/states/lottery-etl-pipeline-prod` is **not** imported; it does not exist
yet and Terraform creates it.

### 5.2 Apply

```bash
terraform apply
```

Expected after the imports: **1 to add** (the SFN log group) **, 8 to change** — the 5
imported groups gaining `retention_in_days = 30` + tags, plus the two IAM policies and the
state machine.

Combined with the artifact churn below, the real prompt reads
**`2 to add, 11 to change, 1 to destroy`** (the layer replacement counts as both an add and
the destroy). Confirmed on the 2026-07-26 apply.

> **If the apply fails with `AccessDeniedException: … logs:CreateLogDelivery`, just re-run
> it.** The only reference from `module.orchestration` into `module.iam` is the role's
> *ARN*, so there was no graph edge to `aws_iam_policy.sfn_execution_policy` — Terraform
> could update the state machine before/alongside the policy that grants it log-delivery
> rights, and Step Functions validates `logging_configuration` during
> `UpdateStateMachine`. The policy is applied by then, so a second `terraform apply` goes
> green; nothing is left half-built. `depends_on = [module.iam]` on the orchestration module
> call now makes the ordering explicit for fresh deploys.

> **⚠️ Expect extra churn that is NOT this PR.** A plan run today already shows
> `1 to add, 3 to change, 1 to destroy` on **master**, before any PR-023 change: rebuilding
> the artifacts produces a new `lambda_layer.zip` hash (pip installs are not byte-
> reproducible) and a changed `lambda_package.zip` (it now carries `src/loteria/gold/` from
> PR-022). That publishes `loteria-deps-prod:N+1` and destroys the old layer version —
> normal, `create_before_destroy` handles the ordering. Verified by planning master with
> the same freshly built zips.

### 5.3 Verify

```bash
# Every group this stack owns now has retention.
aws logs describe-log-groups \
  --query 'logGroups[?starts_with(logGroupName, `/aws/lambda/lottery`) || starts_with(logGroupName, `/aws-glue/`) || starts_with(logGroupName, `/aws/vendedlogs/`)].{name:logGroupName,retention:retentionInDays}' \
  --output table

# Step Functions logging is on.
aws stepfunctions describe-state-machine \
  --state-machine-arn arn:aws:states:us-east-1:913524903233:stateMachine:lottery-etl-pipeline-prod \
  --query 'loggingConfiguration'
```

Expected: `retentionInDays: 30` on all six, and
`{"level": "ALL", "includeExecutionData": true, "destinations": [...vendedlogs...]}`.

Then trigger one execution and confirm log streams land in
`/aws/vendedlogs/states/lottery-etl-pipeline-prod`:

```bash
aws stepfunctions start-execution \
  --state-machine-arn arn:aws:states:us-east-1:913524903233:stateMachine:lottery-etl-pipeline-prod

aws logs describe-log-streams \
  --log-group-name /aws/vendedlogs/states/lottery-etl-pipeline-prod \
  --order-by LastEventTime --descending --max-items 3
```

An empty log group after a successful run means the delivery never got created — check
`AllowSfnLogDeliverySetup` is on `sfn-lottery-policy-prod` (§4).

---

## 6. What this unlocks

PR-024 (dashboard) and PR-025 (alarms) both consume the new module outputs rather than
re-deriving the `/aws/lambda/<fn>` convention:

- `module.etl_lambda.log_group_name`
- `module.etl_glue.log_group_names`
- `module.catalog.crawler_log_group_name`
- `module.orchestration.gold_purge_log_group_name`
- `module.orchestration.state_machine_log_group_name`
