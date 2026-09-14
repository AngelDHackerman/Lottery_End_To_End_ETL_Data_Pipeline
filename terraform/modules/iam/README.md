# Module: `iam`

All IAM roles, customer-managed policies, and attachments for the pipeline: the extractor
Lambda role, Glue job + crawler roles, SageMaker Studio role, and the Step Functions +
EventBridge roles.

**Status:** migrated from `terraform-lottery/Prod/{iam.tf, iam_stepFunctions_eventBridge.tf}`
in **PR-009** via cross-state `terraform state rm` (legacy) + `terraform import` (main) — no
role/policy is recreated. See
[`docs/runbooks/PR-009-iam-migration.md`](../../../docs/runbooks/PR-009-iam-migration.md).

> PR-009 absorbs the Step Function / EventBridge **IAM** (roles + policies) that the
> roadmap originally listed under PR-012's `orchestration` move — because PR-009 must
> output `sfn_execution_role_arn` / `eventbridge_to_sfn_role_arn`. PR-012 moves the
> orchestration **resources** (state machine, event rules) and consumes these role ARNs as
> inputs; `iam_stepFunctions_eventBridge.tf` is already a pointer by then.

## Wildcard tightening (PR-009)
Three grants were narrowed from `"*"` (applied in-place, so the first `plan` after import is
**not** a pure no-op — see the runbook):
- **secretsmanager** (lambda + glue) → the single lottery secret ARN (resolved by name).
- **Step Function glue job actions** → the transform job ARN.
- **Step Function glue crawler actions** → the two silver crawler ARNs.

`logs:*`-style grants keep `Resource = "*"` with a `TODO PR-023` to scope them to explicit
log-group ARNs.

## Personal IAM users (opt-in)
`var.personal_iam_users` (default `[]`) gates the Athena-results grant. A fresh cloner gets
none; the owner lists their own users in a gitignored tfvars.

## Outputs
`lambda_exec_role_arn`, `glue_job_role_arn`, `glue_crawler_role_arn`,
`sfn_execution_role_arn`, `eventbridge_to_sfn_role_arn`, `sagemaker_execution_role_arn`.

## PR-033: `glue_dq_role` — read-only, on purpose

A second Glue role for the Silver data-quality job. Reusing `glue_job_role` would have been
one line, but that role holds `s3:PutObject` and `s3:DeleteObject` on both data buckets
because the transformer writes Silver.

**A validator that can modify what it validates is not a gate.** The value of the DQ job is
an independent assertion that Silver is fine, so the thing asserting it must not be able to
change Silver. `glue_dq_role` gets `s3:GetObject` + `s3:ListBucket` scoped to the Silver
prefix, read on the artifact bucket, and CloudWatch Logs. No write, no delete, no Secrets
Manager.

The Step Function policy also gains:
- `glue:StartJobRun` etc. on the DQ job (the grant is now a **list of two job ARNs**, still
  not a wildcard), and
- `sns:Publish` on the alerts topic, for the `NotifyDQFailure` state.

The topic ARN is built from its name here for the same one-way-dependency reason as
`sfn_log_group_arn` — with the added constraint that `module.observability`, which owns the
topic, already consumes `module.orchestration`, so the output cannot flow back.

Extra inputs: `dq_glue_job_name`, `silver_prefix`. Extra output: `glue_dq_role_arn`.
