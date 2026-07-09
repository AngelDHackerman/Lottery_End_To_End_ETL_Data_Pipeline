# PR-009 — Migrate the `iam` module (cross-state move + wildcard tightening)

**Goal:** Move all IAM roles, customer-managed policies, and attachments from the **legacy**
stack (`terraform-lottery/Prod`, key `legacy/terraform.tfstate`) into
`terraform/modules/iam/` in the **main** stack (key `main/terraform.tfstate`) **without
recreating anything**, AND apply three deliberate wildcard tightenings.

> **Who runs this:** the repo owner, with prod credentials. Same cross-state pattern as
> PR-007/008 (`state rm` + `import`). **Unlike** those PRs, the first main `plan` after
> import is **not** a pure no-op — it shows the intended in-place policy tightening (below),
> which you apply. No role/policy is destroyed or recreated.

## What moves (24 imported + 2 opt-in)

- **6 roles:** `lambda_exec`, `glue_job_role`, `glue_crawler_role`,
  `sagemaker_execution_role`, `sfn_execution_role`, `eventbridge_to_sfn_role`.
- **8 customer-managed policies:** `sagemaker_s3_read_policy`,
  `sagemaker_studio_admin_policy`, `glue_crawler_s3_policy`, `glue_job_policy`,
  `lambda_custom`, `athena_results_access`, `sfn_execution_policy`,
  `eventbridge_to_sfn_policy`.
- **10 role-policy attachments** (see Step 1).
- **2 user-policy attachments** (`santa-lucia-dev`, `angel-adming`) — NOT imported by
  default; gated behind `var.personal_iam_users` (Step 2).

> **Why the SFN/EventBridge IAM moves now (not in PR-012):** the module must output
> `sfn_execution_role_arn` / `eventbridge_to_sfn_role_arn`. PR-012 moves the orchestration
> *resources* and consumes these ARNs.

## The three tightenings (intended in-place diffs)
1. **secretsmanager** in `lambda_custom` + `glue_job_policy`: `"*"` → the single
   `lottery_secret_prod_2` ARN (resolved by name via a data source).
2. **Step Function glue job actions** (`sfn_execution_policy`): `"*"` → the
   `lottery-transform-prod` job ARN.
3. **Step Function glue crawler actions**: `"*"` → the two silver crawler ARNs
   (`lottery-premios-silver-crawler`, `lottery-sorteos-silver-crawler`).

All three are supersets-safe: the pipeline only touches those exact resources.

---

## Prerequisites
```bash
export AWS_PROFILE=angel-adming
export AWS_REGION=us-east-1
```
- The `lottery_secret_prod_2` secret exists (the module resolves its ARN by name).
- Code changes on this branch: iam lives in `terraform/modules/iam/`, the root calls
  `module.iam` (wired to `module.storage` outputs), and the legacy `iam.tf` /
  `iam_stepFunctions_eventBridge.tf` are pointer comments. Legacy files that referenced the
  moved roles (`glue_job.tf`, `glue_crawlers*.tf`, `state_machine.tf`, `eventbridge.tf`,
  `cloudwatch_event_target.tf`, `lambdas.tf`) now use literal role ARNs (same values).

> ⚠️ **Do NOT `terraform apply` the legacy stack until Step 4 verifies a clean plan.**

---

## Step 1 — Import the 24 resources into the MAIN stack
```bash
cd terraform

# --- 6 roles (import id = role name) ---
terraform import module.iam.aws_iam_role.lambda_exec              lottery-lambda-exec-roleprod
terraform import module.iam.aws_iam_role.glue_job_role            glue-lottery-transform-role-prod
terraform import module.iam.aws_iam_role.glue_crawler_role        glue-crawler-role
terraform import module.iam.aws_iam_role.sagemaker_execution_role lottery-sagemaker-execution-role-prod
terraform import module.iam.aws_iam_role.sfn_execution_role       sfn-lottery-execution-role-prod
terraform import module.iam.aws_iam_role.eventbridge_to_sfn_role  eventbridge-to-sfn-role-prod

# --- 8 customer-managed policies (import id = policy ARN) ---
terraform import module.iam.aws_iam_policy.sagemaker_s3_read_policy      arn:aws:iam::913524903233:policy/lottery-sagemaker-s3-read-policy-prod
terraform import module.iam.aws_iam_policy.sagemaker_studio_admin_policy arn:aws:iam::913524903233:policy/lottery-sagemaker-studio-admin-policy-prod
terraform import module.iam.aws_iam_policy.glue_crawler_s3_policy        arn:aws:iam::913524903233:policy/glue-crawler-s3-access
terraform import module.iam.aws_iam_policy.glue_job_policy               arn:aws:iam::913524903233:policy/glue-lottery-transform-policy-prod
terraform import module.iam.aws_iam_policy.lambda_custom                 arn:aws:iam::913524903233:policy/lottery-lambda-customprod
terraform import module.iam.aws_iam_policy.athena_results_access         arn:aws:iam::913524903233:policy/athena-results-s3-access
terraform import module.iam.aws_iam_policy.sfn_execution_policy          arn:aws:iam::913524903233:policy/sfn-lottery-policy-prod
terraform import module.iam.aws_iam_policy.eventbridge_to_sfn_policy     arn:aws:iam::913524903233:policy/eventbridge-to-sfn-policy-prod

# --- 10 role-policy attachments (import id = "role-name/policy-arn") ---
terraform import module.iam.aws_iam_role_policy_attachment.lambda_basic                  "lottery-lambda-exec-roleprod/arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
terraform import module.iam.aws_iam_role_policy_attachment.lambda_custom_attach          "lottery-lambda-exec-roleprod/arn:aws:iam::913524903233:policy/lottery-lambda-customprod"
terraform import module.iam.aws_iam_role_policy_attachment.glue_attach_policy            "glue-lottery-transform-role-prod/arn:aws:iam::913524903233:policy/glue-lottery-transform-policy-prod"
terraform import module.iam.aws_iam_role_policy_attachment.attach_glue_s3                "glue-crawler-role/arn:aws:iam::913524903233:policy/glue-crawler-s3-access"
terraform import module.iam.aws_iam_role_policy_attachment.sagemaker_s3_read_attach      "lottery-sagemaker-execution-role-prod/arn:aws:iam::913524903233:policy/lottery-sagemaker-s3-read-policy-prod"
terraform import module.iam.aws_iam_role_policy_attachment.sagemaker_admin_policy_attach "lottery-sagemaker-execution-role-prod/arn:aws:iam::913524903233:policy/lottery-sagemaker-studio-admin-policy-prod"
terraform import module.iam.aws_iam_role_policy_attachment.sagemaker_full_access         "lottery-sagemaker-execution-role-prod/arn:aws:iam::aws:policy/AmazonSageMakerFullAccess"
terraform import module.iam.aws_iam_role_policy_attachment.cloudwatch_logs_full_access   "lottery-sagemaker-execution-role-prod/arn:aws:iam::aws:policy/CloudWatchLogsFullAccess"
terraform import module.iam.aws_iam_role_policy_attachment.sfn_execution_policy_attachment      "sfn-lottery-execution-role-prod/arn:aws:iam::913524903233:policy/sfn-lottery-policy-prod"
terraform import module.iam.aws_iam_role_policy_attachment.eventbridge_to_sfn_policy_attachment "eventbridge-to-sfn-role-prod/arn:aws:iam::913524903233:policy/eventbridge-to-sfn-policy-prod"
```
If any import says "Resource already managed," skip it.

## Step 2 — (Optional) keep the two personal users' Athena access
Default (`personal_iam_users = []`) drops these grants. To keep them, add a **gitignored**
`terraform/terraform.tfvars` (or `*.auto.tfvars`):
```hcl
personal_iam_users = ["santa-lucia-dev", "angel-adming"]
```
then import the two attachments (id = `user-name/policy-arn`):
```bash
terraform import 'module.iam.aws_iam_user_policy_attachment.personal_athena_results["santa-lucia-dev"]' "santa-lucia-dev/arn:aws:iam::913524903233:policy/athena-results-s3-access"
terraform import 'module.iam.aws_iam_user_policy_attachment.personal_athena_results["angel-adming"]'    "angel-adming/arn:aws:iam::913524903233:policy/athena-results-s3-access"
```
If you leave `personal_iam_users` empty, skip this — the grants are removed from Terraform
management (the attachments stay in AWS until Step 3 removes them from legacy state; they
then become unmanaged. To actually detach them, do it once by hand in the console, or add
them to `personal_iam_users` and let a later `apply` reconcile.)

## Step 3 — Remove the 26 from the LEGACY stack
```bash
cd ../terraform-lottery/Prod

terraform state rm \
  aws_iam_role.lambda_exec \
  aws_iam_role.glue_job_role \
  aws_iam_role.glue_crawler_role \
  aws_iam_role.sagemaker_execution_role \
  aws_iam_role.sfn_execution_role \
  aws_iam_role.eventbridge_to_sfn_role \
  aws_iam_policy.sagemaker_s3_read_policy \
  aws_iam_policy.sagemaker_studio_admin_policy \
  aws_iam_policy.glue_crawler_s3_policy \
  aws_iam_policy.glue_job_policy \
  aws_iam_policy.lambda_custom \
  aws_iam_policy.athena_results_access \
  aws_iam_policy.sfn_execution_policy \
  aws_iam_policy.eventbridge_to_sfn_policy \
  aws_iam_role_policy_attachment.lambda_basic \
  aws_iam_role_policy_attachment.lambda_custom_attach \
  aws_iam_role_policy_attachment.glue_attach_policy \
  aws_iam_role_policy_attachment.attach_glue_s3 \
  aws_iam_role_policy_attachment.sagemaker_s3_read_attach \
  aws_iam_role_policy_attachment.sagemaker_admin_policy_attach \
  aws_iam_role_policy_attachment.sagemaker_full_access \
  aws_iam_role_policy_attachment.cloudwatch_logs_full_access \
  aws_iam_role_policy_attachment.sfn_execution_policy_attachment \
  aws_iam_role_policy_attachment.eventbridge_to_sfn_policy_attachment \
  aws_iam_user_policy_attachment.attach_results_user_dev \
  aws_iam_user_policy_attachment.attach_results_user_adming
```
(The three `data.aws_iam_policy_document.*` and two `data.aws_iam_user.*` data sources drop
automatically once the config no longer declares them — no `state rm` needed.)

## Step 4 — Verify the MAIN plan (tightening)
```bash
cd ../../terraform
terraform plan
```
**Predicted:** `0 to add, 3 to change, 0 to destroy` — in-place updates to
`module.iam.aws_iam_policy.glue_job_policy`, `.lambda_custom`, and `.sfn_execution_policy`
(the secret + glue ARN narrowings), then `terraform apply` and re-plan to `No changes.`
- ❌ Any **create** = a missed import (re-run it). Any **destroy/replace** = STOP.

> **✅ ACTUAL outcome (owner ran 2026-07-08): `No changes.` — no apply needed.**
> The live prod policies had **already** been narrowed by hand during the manual buildout
> (secretsmanager → `lottery_secret_prod_2-NKfmAe`; SFN glue → the job + two silver crawler
> ARNs). The legacy `.tf` showed stale `"*"` wildcards that never matched reality. Since the
> module config equals the real (already-narrowed) policies, `import` produced a clean plan.
> PR-009's real value here is **codifying** that narrowing in version control — the security
> posture was already correct in AWS; it just wasn't captured (and was misrepresented) in
> the repo. If your account's live policies still hold wildcards, you'd instead see the
> predicted `3 to change` and would `apply`.

## Step 5 — Verify the LEGACY plan is a no-op
```bash
cd ../terraform-lottery/Prod && terraform plan
```
**Expected:** `No changes.`
- ⚠️ Acceptable: the pre-existing `aws_s3_object.lambda_package` etag diff (unrelated, see
  PR-004/007/008 notes).
- ❌ Any **destroy** of an IAM resource = the `state rm` missed an address. Do not apply.

## Step 6 — Smoke-test the pipeline (tightening safety)
Start the Step Function once (console or CLI) and confirm a full run succeeds — this proves
the narrowed secret + glue grants still permit extractor Lambda → Glue job → both silver
crawlers.

> Now **optional/confirmatory**: since Step 4 was a no-op, the pipeline already runs under
> these exact (already-narrowed) policies — nothing about its permissions changed.
```bash
aws stepfunctions start-execution --state-machine-arn \
  arn:aws:states:us-east-1:913524903233:stateMachine:lottery-etl-pipeline-prod
```

---

## Rollback
Nothing structural changed in AWS. To revert: re-import the 24 (+2) into legacy at their
non-`module.iam` addresses and `state rm module.iam.*` from main; then `git revert`. The
policy narrowings revert by re-applying the old wildcard config (the old policy versions).

## What this PR touches
- **Adds:** `terraform/modules/iam/{main,variables,outputs}.tf` + README; wires `module.iam`
  into the root (from `module.storage` outputs); adds root vars `lottery_secret_name`,
  `personal_iam_users`.
- **Edits (legacy, code only):** `iam.tf` + `iam_stepFunctions_eventBridge.tf` → pointers;
  6 files' role references → literal ARNs; `lambdas.tf` drops the moved attachment from
  `depends_on`.
- **State ops (owner):** import 24 (+2 opt-in) into main; `state rm` 26 from legacy.
- **Live change:** none, in this account — the 3 policy narrowings were already applied by
  hand in prod, so the module just codifies them (see Step 4). In an account still holding
  the wildcards, the owner would apply the 3 narrowings. No role/attachment recreated.
