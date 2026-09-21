# Roadmap — Loteria Santa Lucia, "Hiring Manager Ready"
**Owner:** Angel Hernandez
**Companion doc:** [`DoD.md`](./DoD.md) (vision + locked decisions)
**Last updated:** 2026-09-16

> This is the **execution plan**. Each PR below is atomic, independently reviewable, and prompt-ready for Claude Code / Codex. Work them top-to-bottom unless a dependency is noted.
>
> **Ground rules**
> - One PR = one logical change. Many small PRs over a few big ones.
> - Stay on the `master` branch — feature branches named `feat/PR-NNN-short-slug` → PR into `master`.
> - Never delete data in S3. Never `terraform destroy` against the prod buckets until they have `prevent_destroy = true` + S3 Versioning enabled.
> - Every PR must update the **PR Tracker** table at the bottom of this file (set status, link the PR).
> - Tests must pass locally before opening the PR. CI will gate once Phase 5 is in.
> - The owner's focus is **Data Quality + MLOps**, not generic DevOps — when in doubt, optimize for showcasing data correctness, lineage, observability, and reproducibility.

---

## How to use this file with an AI coding agent

Copy-paste the **"Prompt"** block of the target PR into Claude Code / Codex. Each prompt is self-contained:
- Goal
- Files to touch / create
- Acceptance criteria
- Verification steps
- Out-of-scope (so the agent doesn't sprawl)

After the agent finishes:
1. `git diff` and review.
2. Update the PR Tracker (status + PR link).
3. Move on to the next PR.

---

# Phase 0 — Safety net
Do these first. Goal: make the existing prod data unkillable before any refactor.

## PR-001 — Repo hygiene baseline
**Goal:** Strip committed scratch files, add tooling pins, set up `pyproject.toml`, `pre-commit`, `Makefile` skeleton. No behavior change yet.

**Prompt:**
```
You are working in the Loteria_Project repo. Read DoD.md and roadmap.md first.

Task PR-001:
1. Delete committed scratch / artifact files:
   - modules/ETL/Prod/temp_files/ (entire folder, contains .parquet)
   - terraform-lottery/Prod/temp_tf_files/
   - miscellaneous/output.txt
2. Update .gitignore to keep *.parquet, *.zip, build/, .terraform/, .vscode/ ignored (some already there — dedupe).
3. Create pyproject.toml at the repo root using `uv`-compatible PEP 621 metadata:
   - python = "^3.12"
   - project name "loteria-santa-lucia"
   - dev deps: pytest, pytest-cov, ruff, black, mypy, moto, great-expectations, nbstripout, pre-commit
   - runtime deps: requests, beautifulsoup4, pandas, pyarrow, python-dateutil, boto3
4. Add .pre-commit-config.yaml with: ruff, ruff-format, terraform_fmt, nbstripout, end-of-file-fixer, trailing-whitespace.
5. Create Makefile skeleton with empty targets that just `echo`: bootstrap, secrets, build, deploy, test, destroy, lint, fmt, tf-plan, sagemaker. We'll fill them in later PRs.
6. Add a `.python-version` file pinning 3.12.

Do NOT change any application or Terraform code. Do NOT delete the notebooks or images.

Verify:
- `git status` shows only the listed changes.
- `python -c "import tomllib; tomllib.load(open('pyproject.toml','rb'))"` succeeds.
- `pre-commit run --all-files` runs (failures OK, we just want the config to parse).
```

**Acceptance:** Repo has clean baseline tooling. No functional regressions. Commit message: `chore: PR-001 repo hygiene baseline`.

---

## PR-002 — Inventory and protect prod buckets (no Terraform yet)
**Goal:** Prove what's in prod and turn on Versioning + add object protection — *via AWS CLI*, before touching TF. This is the safety belt for everything that follows.

**Prompt:**
```
Read DoD.md §"Phase 0" and roadmap.md PR-002.

Task: produce a bash script `scripts/00_inventory_and_protect.sh` that, given AWS_PROFILE and AWS_REGION env vars:

1. For each of these buckets:
   - lottery-partitioned-storage-prod
   - lottery-data-simple-prod
   Do:
   a. `aws s3 ls --summarize --recursive s3://<bucket>` and pipe the totals (object count, total bytes) into docs/inventory/<bucket>_<UTC_DATE>.txt
   b. Enable versioning: `aws s3api put-bucket-versioning --bucket <bucket> --versioning-configuration Status=Enabled`
   c. Attach a bucket policy that DENIES s3:DeleteBucket and s3:DeleteObject* to everyone except the bucket owner root principal. Save the policy JSON under scripts/policies/<bucket>_protect.json and apply with `aws s3api put-bucket-policy`.
   d. Print a green "✅ <bucket> protected" line.

2. The script must be idempotent (re-running is safe). Use `set -euo pipefail`.

3. Add a one-paragraph README to docs/inventory/README.md explaining what the snapshots are for.

4. Do NOT enable Object Lock (it can only be enabled at bucket creation; we'll address that in a later, deliberate PR).

5. Do NOT touch Terraform.

Verify locally by DRY-RUNNING the script (echo the AWS commands instead of executing) and pasting the dry-run output into the PR description. Owner will run for real.
```

**Acceptance:** Owner runs the script, both buckets show `Versioning: Enabled`, deny-delete policy is in place, inventory file is committed.

---

## PR-003 — Bootstrap remote state backend (S3 + DynamoDB)
**Goal:** A small, separate Terraform stack that creates the state bucket + lock table. Run once, then the main stack uses it.

**Prompt:**
```
Create `terraform/bootstrap/` containing:
- main.tf: aws_s3_bucket "tf_state" (name "loteria-tf-state-<aws_account_id>"), versioning enabled, SSE-S3, public access block, prevent_destroy = true.
- dynamodb.tf: aws_dynamodb_table "tf_locks" (name "loteria-tf-locks", hash_key "LockID", PAY_PER_REQUEST).
- variables.tf: aws_region (default us-east-1), aws_account_id (required).
- outputs.tf: state_bucket_name, lock_table_name.
- provider.tf: aws ~> 5.0, terraform >= 1.6.
- README.md explaining "run once: `terraform init && terraform apply`, then copy the outputs into ../backend.hcl".

Also create `terraform/backend.hcl.example` documenting the bucket / key / region / dynamodb_table values to be filled in.

Do NOT migrate the existing terraform-lottery/Prod state yet — that's PR-004.
```

**Acceptance:** Owner can `cd terraform/bootstrap && terraform apply` in their account and get a clean state backend.

---

## PR-004 — Move existing TF state to remote backend (no resource changes)
**Goal:** Same resources, remote state. Verify the `plan` is empty after migration.

> **⚠️ Plan change during execution (2026-07-02):** the legacy `terraform-lottery/Prod`
> state was found to be **lost** — gitignored (`*.tfstate`), never committed, no local
> copy. The 67 resources still exist in AWS. So PR-004 became a **state reconstruction
> via `terraform import`** instead of a state move. Deliverables: `backend.tf` (fresh
> S3 backend, no `-migrate-state`), `scripts/reconstruct_legacy_state.sh` (idempotent
> bulk import), and `docs/runbooks/PR-004-state-migration.md`. Three resources can't be
> imported (2 `null_resource`, 1 `aws_iam_policy_attachment`) — commented out, handled
> in PR-009/PR-012. Acceptance is unchanged: `terraform plan` == no-op after import.

**Prompt:**
```
Read PR-003's outputs (the state bucket + lock table).

Task:
1. Add backend.tf to terraform-lottery/Prod/ pointing to s3 backend with key "legacy/terraform.tfstate", dynamodb_table = "loteria-tf-locks".
2. Document the migration steps in docs/runbooks/PR-004-state-migration.md:
   - `terraform init -migrate-state -backend-config=../backend.hcl`
   - `terraform plan` MUST show "No changes". If it doesn't, STOP and open an issue.
3. Do not touch any .tf resource — only the backend block + the runbook.

Owner will perform the migration. Agent only writes the files + runbook.
```

**Acceptance:** Plan is empty after migration. State file appears in the new S3 bucket.

---

## PR-005 — Import existing buckets into Terraform with `prevent_destroy`
**Goal:** Uncomment the bucket resources in `s3.tf`, `terraform import` them, add `prevent_destroy = true`, `versioning`, `server_side_encryption`, `public_access_block`. Plan must be empty.

**Prompt:**
```
In terraform-lottery/Prod/s3.tf:

1. Uncomment aws_s3_bucket "lottery_raw_data" (rename to "lottery_partitioned") and aws_s3_bucket "lottery_data_simple" (rename to "lottery_simple").
2. For BOTH:
   - bucket name interpolation must match the existing real names: lottery-partitioned-storage-prod and lottery-data-simple-prod respectively.
   - lifecycle { prevent_destroy = true }
   - Add aws_s3_bucket_versioning resources (Enabled, since we already enabled it in PR-002).
   - Add aws_s3_bucket_server_side_encryption_configuration (AES256).
   - Add aws_s3_bucket_public_access_block (all four to true).

3. Write docs/runbooks/PR-005-bucket-import.md with the exact `terraform import` commands:
   - terraform import aws_s3_bucket.lottery_partitioned lottery-partitioned-storage-prod
   - terraform import aws_s3_bucket.lottery_simple lottery-data-simple-prod
   - and any sub-resource imports needed (versioning, encryption, PAB).

4. After import, `terraform plan` MUST show zero changes (or only no-op metadata).

Hard constraint: do NOT add `force_destroy = true`. Do NOT remove the existing protection bucket policy from PR-002.
```

**Acceptance:** Both buckets are managed by Terraform; plan is empty; `prevent_destroy` is set.

---

# Phase 1 — Reproducible Terraform (modules)
Single env, single root caller. No `envs/dev` `envs/prod` (per DoD §4 decision).

## PR-006 — Module skeleton + `terraform/` root caller
**Goal:** Create the new home (`terraform/`) without moving any resources yet. Make the structure visible so subsequent PRs can move one module at a time.

**Prompt:**
```
Create the following empty Terraform modules (each with main.tf, variables.tf, outputs.tf, README.md — files can be near-empty placeholders with the module's intent):
- terraform/modules/network/
- terraform/modules/storage/
- terraform/modules/iam/
- terraform/modules/etl-lambda/
- terraform/modules/etl-glue/
- terraform/modules/orchestration/   # Step Functions + EventBridge
- terraform/modules/observability/   # CloudWatch dashboards/alarms, SNS
- terraform/modules/catalog/         # Glue DB + crawlers
- terraform/modules/lake-formation/

Create terraform/main.tf (root caller) that references each module with TODO comments — no actual wiring yet.
Create terraform/variables.tf, terraform/outputs.tf, terraform/provider.tf, terraform/backend.tf (pointing at the bootstrap backend, key "main/terraform.tfstate").

Do NOT delete terraform-lottery/Prod/ yet. Both folders will coexist for a few PRs.
`terraform init && terraform plan` in terraform/ should succeed and show nothing to create (because modules are empty).
```

**Acceptance:** New folder structure compiles. Old folder untouched.

---

## PR-007 — Migrate `storage` module (the imported buckets)
**Prompt:**
```
Move the bucket resources created in PR-005 from terraform-lottery/Prod/s3.tf into terraform/modules/storage/.

- Module exposes outputs: partitioned_bucket_name, partitioned_bucket_arn, simple_bucket_name, simple_bucket_arn, athena_results_bucket_name, lambda_code_bucket_name.
- Also move the athena_results bucket and lambda_code_zip bucket here.
- Root terraform/main.tf wires up the module.

Migration uses `terraform state mv` (document in docs/runbooks/PR-007-storage-migration.md). Final `terraform plan` from terraform/ must be empty.

Delete the moved resources from terraform-lottery/Prod/s3.tf (leave the file with only a comment pointer).
```

**Acceptance:** Buckets now managed under the new module path; no resource churn.

---

## PR-008 — Migrate `network` module (VPC, subnets, NAT, IGW, endpoints, SGs)
**Prompt:**
```
Move terraform-lottery/Prod/network.tf into terraform/modules/network/.
Expose outputs: vpc_id, private_subnet_ids, public_subnet_id, sagemaker_sg_id.
Use `terraform state mv` for every resource. Final plan must be empty.
Keep `var.enable_internet` as a module variable, default false.
```

**Acceptance:** Network resources owned by module; no churn.

---

## PR-009 — Migrate `iam` module (clean up wildcards, parameterize users)
**Prompt:**
```
Move terraform-lottery/Prod/iam.tf into terraform/modules/iam/. While moving:

1. Tighten wildcards:
   - secretsmanager:GetSecretValue → resource = the specific lottery secret ARN (passed in as a module input).
   - logs:* → keep wildcard for now but add a TODO comment.
   - glue:* in Step Function policy → narrow to the specific job + crawler ARNs from outputs.

2. Gate the two personal IAM-user attachments (santa-lucia-dev, angel-adming) behind a variable:
   `variable "personal_iam_users" { type = list(string); default = [] }`
   If empty, the `aws_iam_user_policy_attachment` resources are not created (`for_each = toset(var.personal_iam_users)`). The owner's own tfvars can set the list; a fresh cloner gets nothing.

3. Use `terraform state mv` for all existing resources. Plan must be empty (excluding the personal-user attachments, which may be expected removes — document in the runbook).

Module outputs: lambda_exec_role_arn, glue_job_role_arn, glue_crawler_role_arn, sfn_execution_role_arn, eventbridge_to_sfn_role_arn, sagemaker_execution_role_arn.
```

**Acceptance:** IAM module owns roles; personal-user references are opt-in; plan is clean.

---

## PR-010 — Migrate `etl-lambda` module
**Prompt:**
```
Move terraform-lottery/Prod/lambdas.tf into terraform/modules/etl-lambda/.

Module inputs: lambda_code_bucket, lambda_zip_key, lambda_exec_role_arn, partitioned_bucket_name, simple_bucket_name, secret_name, region.
Module outputs: extractor_lambda_arn, extractor_lambda_name.

Replace the env vars in the function so they pass *bucket names* (not ARNs) and the secret name. Adjust accordingly in PR-013 (code cleanup).

`terraform state mv` to preserve the function. Plan must be empty.
```

**Acceptance:** Extractor Lambda lives under the new module.

---

## PR-011 — Migrate `etl-glue` module (and drop hard-coded script_location)
**Prompt:**
```
Move terraform-lottery/Prod/glue_job.tf into terraform/modules/etl-glue/.

Required changes:
- Remove the hard-coded `s3://lambda-code-zip-prod/lottery_transformer.zip`. Replace with `s3://${var.code_bucket}/${var.script_key}`.
- Expose inputs: code_bucket, script_key, partitioned_bucket_name, simple_bucket_name, glue_job_role_arn, glue_version (default "3.0"), python_version (default "3.9").
- Add a TODO comment for the Glue 4.0 / Py3.10 upgrade spike.
- Output: glue_job_name, glue_job_arn.

Use `terraform state mv`. Plan must be empty.
```

**Acceptance:** Glue job is portable; no hard-coded ARNs.

---

## PR-012 — Migrate `catalog` + `orchestration` modules, kill duplicate EventBridge rule
**Prompt:**
```
1. catalog module: move glue_crawlers.tf AND glue_crawlers_silver.tf into terraform/modules/catalog/.
   - DELETE the legacy `processed/` crawlers (premios_crawler, sorteos_crawler) — they point at a prefix the new transformer no longer writes. Add a one-line note in the module README that the underlying S3 prefix `processed/` is preserved (not deleted).
   - DELETE both `null_resource "run_glue_crawlers"` blocks — the Step Function starts the crawlers; we don't need apply-time triggers.
   - Outputs: db_name, premios_silver_crawler_name, sorteos_silver_crawler_name.

2. orchestration module: move state_machine.tf, eventbridge.tf, cloudwatch_event_rule.tf, cloudwatch_event_target.tf, iam_stepFunctions_eventBridge.tf.
   - DELETE the duplicate: keep `weekly_etl_trigger` (eventbridge.tf, cron(0 18 ? * MON *)) and DELETE `weekly_trigger` (cloudwatch_event_rule.tf, cron(0 14 ? * 6 *)). Document the decision in the module README.
   - Update Step Function to reference the new silver crawlers from the catalog module outputs (not var strings).

Use `terraform state mv` where resources are preserved; `terraform state rm` (NOT destroy) for resources being deleted from code but kept in AWS. For the duplicate EventBridge rule, allow Terraform to destroy it (it's the unwanted one).
```

**Acceptance:** One weekly cron. One set of crawlers. State machine references real resources.

---

## PR-013 — Codify Lake Formation permissions
**Prompt:**
```
Move terraform-lottery/Prod/lake_formation.tf into terraform/modules/lake-formation/.

Codify the manual permissions documented in challanges_faced.md §5:
- aws_lakeformation_resource for the `silver/` prefix of the partitioned bucket, registered with the AWSServiceRoleForLakeFormationDataAccess.
- aws_lakeformation_permissions: grant DESCRIBE+SELECT on the database `lottery_santalucia_db` to the glue_crawler_role.
- aws_lakeformation_permissions: grant CREATE_TABLE, ALTER, DROP, DESCRIBE on the database to the glue_crawler_role.
- aws_lakeformation_permissions: grant DATA_LOCATION_ACCESS on the silver path to the glue_crawler_role.
- IAMAllowedPrincipals compatibility grant: gated behind variable `enable_iam_allowed_principals_compat` (default true), with a comment explaining when to disable.

Test in the owner's account by running `terraform apply` and triggering the silver crawlers manually — they must succeed without manual console clicks.
```

**Acceptance:** A fresh deploy in a new account does not require any Lake Formation console clicks.

---

## PR-014 — Migrate `observability` module (placeholder for Phase 4)
**Prompt:**
```
Create terraform/modules/observability/ with placeholder main.tf containing only:
  resource "aws_sns_topic" "alerts" { name = "loteria-alerts-${var.environment}" }
Module input: alert_email (optional). If set, create aws_sns_topic_subscription "email_alerts".
Module output: alerts_topic_arn.

Phase 4 PRs (PR-024..PR-028) will fill in dashboards + alarms.
```

**Acceptance:** SNS topic exists; email subscription works.

---

## PR-015 — Migrate `sagemaker` to optional module + delete `terraform-lottery/Prod/`
**Prompt:**
```
1. Move terraform-lottery/Prod/sagemaker.tf into terraform/modules/sagemaker/.
2. In terraform/main.tf, wrap the sagemaker module with `count = var.enable_sagemaker ? 1 : 0`. Default false.
3. Update Makefile target `sagemaker`: `terraform apply -var=enable_sagemaker=true -target=module.sagemaker`.
4. After confirming every resource has moved (`grep -r aws_ terraform-lottery/Prod/` returns nothing actionable), DELETE the entire terraform-lottery/ folder. Document in commit message that all state was migrated via `terraform state mv` in PRs 007–014.
5. Update README to point at terraform/ instead of terraform-lottery/Prod/.
```

**Acceptance:** Single root: `terraform/`. Old folder gone. SageMaker is opt-in.

---

# Phase 2 — Code cleanup

## PR-016 — Single source of truth: `src/` layout
**Prompt:**
```
Consolidate the two parallel code trees:

1. Create src/loteria/{extractor,transformer,parser,common}/.
2. Move the *current, working* code into src/loteria/:
   - Extractor: from lambda/extractor/ (it's the Lambda)
   - Transformer + parser: from glue_job_transformer/ (it's the Glue job's source of truth)
   - common: aws_secrets.py, s3_utils.py (deduplicate the two near-identical copies; keep the more complete one and add tests later)
3. DELETE lambda/ and glue_job_transformer/ folders entirely.
4. DELETE modules/ETL/Prod/ scratch scripts (extract.py, hacker_rank.py, transformer_dry_test.py, etc.) — they're stale duplicates.
5. Update all import statements (`from extractor.x` → `from loteria.extractor.x`).
6. Update Glue job script_key path in tfvars docs to reflect the new layout.

Do NOT change runtime logic. The diff should be moves + import path edits + deletions.
```

**Acceptance:** One Python package, `loteria`. No duplicate modules.

---

## PR-017 — Parameterize hard-coded config
**Prompt:**
```
In src/loteria/common/aws_secrets.py:
- Read secret_name from env var LOTERIA_SECRET_NAME (default "lottery_secret_prod_2").
- Read region from env var AWS_REGION (default "us-east-1").
- Replace the brittle `.split(":::")[-1]` ARN parser with a proper extractor (the secret payload should store bucket *names*, not ARNs — flag this as a follow-up).

Update terraform/modules/etl-lambda and etl-glue to pass LOTERIA_SECRET_NAME as an env var / job argument.
```

**Acceptance:** Cloning into a new account only requires changing the secret name in one place.

---

## PR-018 — Structured JSON logging
**Prompt:**
```
1. Add src/loteria/common/logging_setup.py:
   - Function `configure_logging(service_name: str) -> logging.Logger` that installs a JSON formatter (use `python-json-logger`, add to runtime deps).
   - Include fields: timestamp, level, message, service, correlation_id (read from env var CORRELATION_ID, default to a generated UUID).
2. Replace all `print(...)` calls in src/loteria/ with `logger.info/warning/error`.
3. Each entry point (lambda_handler.py, transformer/__main__.py) calls configure_logging() on startup.
4. Update the Step Function definition to pass `CORRELATION_ID.$` = "$$.Execution.Name" to the Lambda and Glue Job.
```

**Acceptance:** CloudWatch logs are valid JSON with a correlation id matching the Step Function execution name.

---

## PR-019 — Lambda Layer for heavy deps
**Prompt:**
```
1. Create scripts/build_lambda_layer.sh that produces layer.zip containing requests + beautifulsoup4 (+ their transitive deps), structured as python/lib/python3.12/site-packages/...
2. Replace build_lambda_package.sh with scripts/build_lambda_function.sh that produces a *thin* code.zip containing only src/loteria/ (no deps).
3. In terraform/modules/etl-lambda/, add aws_lambda_layer_version "loteria_deps" and attach `layers = [aws_lambda_layer_version.loteria_deps.arn]` to the extractor function.
4. Wire `make build` to call both scripts.
5. Verify the function still cold-starts under 3s (manual smoke test by the owner — document in the PR).
```

**Acceptance:** Function zip < 5 MB. Layer zip handles deps.

---

## PR-020 — Glue Job upgrade spike (Glue 4.0 / Python 3.10)
**Prompt:**
```
1. Change terraform/modules/etl-glue defaults: glue_version = "4.0", python_version = "3.10".
2. Run one Glue job execution manually in the owner's account. Capture the CloudWatch log link in the PR description.
3. If it fails, REVERT the defaults and open a follow-up issue with the failure log attached. Do not merge a broken upgrade.

Acceptance: Glue 4.0 / Py 3.10 is on, or we have a documented reason to stay on 3.0/3.9.
```

> **OUTCOME (2026-07-21): documented stay on Python Shell 3.9.** The target is invalid for
> this job type. The transform is a **Python Shell** job, which supports only Python 3.6/3.9
> (3.6 EOL 2026-03-01) — there is no 3.10 — and `glue_version` is **ignored** for Python
> Shell (AWS stores it, the live job reads back `"3.0"`, but "Glue 4.0/5.0" are Spark-only).
> A newer runtime would require migrating the job **type** to Spark (`glueetl`) or Ray — a
> transformer rewrite, filed as a deferred item (see L6 below), not a version bump. Docs-only
> change; `terraform plan` stays a no-op. Runbook: `docs/runbooks/PR-020-glue-runtime-spike.md`.

---

# Phase 3 — Gold layer (Athena CTAS)

## PR-021 — Gold table SQL definitions
**Prompt:**
```
Create sql/gold/ containing one CTAS SQL file per table from DoD.md §"Phase 3":
- 01_gold_draw_summary.sql
- 02_gold_winning_number_frequency.sql
- 03_gold_terminations.sql
- 04_gold_letters_distribution.sql
- 05_gold_geo_winnings.sql
- 06_gold_vendor_leaderboard.sql
- 07_gold_time_series.sql

Each file follows the pattern:
  CREATE TABLE lottery_santalucia_db.gold_<name>
  WITH (
    format = 'PARQUET',
    external_location = 's3://<partitioned_bucket>/gold/<name>/',
    partitioned_by = ARRAY[...]   -- if applicable
  ) AS
  SELECT ...
  FROM lottery_santalucia_db.silver_premios_premios p
  JOIN lottery_santalucia_db.silver_sorteos_sorteos s ON p.numero_sorteo = s.numero_sorteo
  ...;

Constraints:
- Use only the *silver* tables (the ones with `silver_` prefix from PR-012).
- Partition `gold_geo_winnings`, `gold_vendor_leaderboard`, `gold_time_series` by year for cheap scans.
- Add a corresponding DROP TABLE IF EXISTS at the top of each file so re-runs are idempotent.

Do NOT execute the SQL yet. Just commit the files. The owner will run each manually in the Athena console once to validate before PR-022 automates them.
```

**Acceptance:** 7 SQL files. Owner runs at least 2–3 of them by hand and pastes a row count into the PR.

---

## PR-022 — Wire Gold into Step Function
**Prompt:**
```
1. Add an S3 prefix `sql/gold/` under the partitioned bucket. Upload all SQL files from PR-021 there via a Terraform aws_s3_object for_each over fileset("sql/gold", "*.sql").
2. Extend the Step Function (terraform/modules/orchestration/state_machine.tf):
   - After RunSorteosCrawler, add a Map state "BuildGold" with one iteration per SQL file.
   - Each iteration calls arn:aws:states:::athena:startQueryExecution.sync with the file contents (loaded via States.Format from S3 — simplest is to inline a SELECT against the result_configuration of the workgroup).
   Alternative if loading SQL from S3 in SFN is painful: hard-code the 7 query strings as a States.Choice. Pick whichever is more readable.
3. Update SFN IAM (iam_stepFunctions_eventBridge.tf) to allow:
   - athena:StartQueryExecution, athena:GetQueryExecution
   - s3:GetObject on the partitioned bucket sql/gold/ prefix
   - s3:PutObject on the athena_results bucket
   - glue:CreateTable, glue:GetTable, glue:UpdateTable on the lottery_santalucia_db
4. After Gold queries succeed, add a final state "RunGoldCrawler" — a new crawler defined in catalog module that crawls s3://<partitioned>/gold/ and registers tables under prefix `gold_`.
```

**Acceptance:** A full Step Function run from cold produces Bronze → Silver → Gold and the new gold_* tables are queryable in Athena.

---

# Phase 4 — Observability (fleshes out PR-014's placeholder)

PRs in this phase can land in any order, but PR-023 first.

## PR-023 — Log retention everywhere
**Prompt:**
```
In terraform/modules/etl-lambda, etl-glue, orchestration, catalog: create aws_cloudwatch_log_group resources EXPLICITLY (instead of letting AWS auto-create them) with retention_in_days = 30.

For each existing service that auto-creates a log group, either:
(a) `terraform import` the existing group and set retention, or
(b) Pre-create the group with the canonical name (e.g. /aws/lambda/<function-name>) — AWS will reuse it.

Add a variable `log_retention_days` (default 30) so the owner can crank it up for prod.
```

> **Scope notes discovered while executing (2026-07-26):**
> - **Glue has no per-job/per-crawler log groups.** A Python Shell job writes to the
>   account-wide `/aws-glue/python-jobs/{output,error}`, crawlers to `/aws-glue/crawlers`
>   (`--continuous-log-logGroup` is Spark-only — same job-family split as PR-020). Setting
>   retention therefore means owning three account-shared groups, gated behind
>   `manage_shared_glue_log_groups` (default true).
> - **The orchestration module gained Step Functions execution logging**, which was OFF —
>   the pipeline had no CloudWatch record of a run at all. New group
>   `/aws/vendedlogs/states/…` (prefix is mandatory), `sfn_log_level` default `ALL`.
> - Resolves PR-009's two `TODO PR-023` IAM wildcards: the Glue one narrows to
>   `/aws-glue/*`; the SFN one splits, and its delivery half **must** stay `"*"` because AWS
>   documents those actions as not supporting resource-level permissions.
> - 5 of the 6 groups already exist and must be **imported**. Runbook:
>   `docs/runbooks/PR-023-log-retention.md`.

## PR-024 — CloudWatch dashboard
**Prompt:**
```
Add aws_cloudwatch_dashboard "loteria_pipeline" in terraform/modules/observability/ with widgets:
- Step Function: ExecutionsSucceeded, ExecutionsFailed, ExecutionTime (p50/p95/p99)
- Lambda extractor: Errors, Throttles, Duration
- Glue Job: glue.driver.aggregate.numCompletedTasks, glue.ALL.s3.filesystem.read_bytes
- S3 object counts under raw/, silver/, gold/ (via a tiny custom metric pushed by a 1-min Lambda — defer the Lambda part to PR-027 if heavy)
- Athena: QueryQueueTime, EngineExecutionTime, ProcessedBytes for workgroup "lottery-wg"
```

> **⚠️ The two Glue widgets above are IMPOSSIBLE for this job (verified live 2026-07-26).**
> `glue.driver.aggregate.numCompletedTasks` and `glue.ALL.s3.filesystem.read_bytes` are
> **Spark** metrics; the transform is a Python Shell job and publishes no job telemetry.
> The whole `AWS/Glue` namespace holds one metric — `ResourceUsage`, an account-level
> service-quota gauge with **no `JobName` dimension** — and there are **no crawler metrics
> at all**. Same pythonshell-vs-`glueetl` split as PR-020.
>
> **Substitute:** Step Functions *service-integration* metrics (`AWS/States`,
> `ServiceIntegrationResourceArn`) give per-stage success/failure/duration for the Glue job,
> the crawlers and the Athena CTAS. Gotcha: that dimension's value is **account-qualified**
> (`arn:aws:states:us-east-1:<acct>:glue:startJobRun.sync`, not the bare
> `arn:aws:states:::glue:...` used in the state machine) and identifies the integration
> **type**, not the resource. Glue-specific detail comes from Logs Insights widgets over the
> PR-023 log groups. S3 object counts deferred to PR-027 as the prompt allows.

## PR-025 — Alarms
**Prompt:**
```
Add aws_cloudwatch_metric_alarm resources, each notifying SNS topic from PR-014:
1. SFN_ExecutionFailed: AWS/States ExecutionsFailed > 0 over 5 min
2. SFN_NoSuccessIn8Days: AWS/States ExecutionsSucceeded < 1 over 8 days (composite or expression alarm; choose simplest)
3. Lambda_Errors: AWS/Lambda Errors > 0 over 5 min for the extractor
4. Glue_JobFailed: AWS/Glue Job.failure > 0
5. Crawler_Failed: AWS/Glue glue.driver.aggregate.numFailedTasks > 0 on each silver/gold crawler
6. ScrapeDo_Failed: alarm on the "ScraperHttpStatus" custom metric from PR-026 when any non-200 StatusCode is emitted (esp. 401/402/429 — auth/quota/rate-limit). scrape.do is a third-party proxy on the FREE TIER; if the free plan ends or the quota is hit, the weekly run breaks. Today this only surfaces indirectly (fetch_via_proxy raises on non-200 → Lambda_Errors + SFN_ExecutionFailed fire), so this dedicated alarm names the real cause instead of a generic Lambda error. Depends on PR-026's metric — if ordering, land PR-026 first.
```

> **⚠️ Alarms 4 and 5 hit the same dead end as PR-024's Glue widgets.** `AWS/Glue`
> `Job.failure` and `glue.driver.aggregate.numFailedTasks` do **not exist** for a Python
> Shell job or for crawlers — confirmed live 2026-07-26, the namespace has only
> `ResourceUsage`. Alarm them on `AWS/States` `ServiceIntegrationsFailed` with
> `ServiceIntegrationResourceArn` = the account-qualified `glue:startJobRun.sync` /
> `aws-sdk:glue:startCrawler` values instead (see the PR-024 note), or on a CloudWatch Logs
> metric filter over `/aws-glue/python-jobs/error`. Alarm 2 (`NoSuccessIn8Days`) also needs
> care: `ExecutionsSucceeded` reports **no datapoints** rather than zero when nothing runs,
> so the alarm must treat missing data as breaching.

> **Notes from executing it (2026-08-02):**
> - **8 days is not possible — the alarm is 7.** CloudWatch caps an alarm's total evaluation
>   window: "`Period` multiplied by `EvaluationPeriods` can't be more than 604,800 seconds."
>   8 × 86,400 = 691,200 and the API rejects it; the cap is on the window itself, so no
>   composite/expression form gets around it. 7 × 86,400 is the exact ceiling **and** the
>   right number for a weekly trigger — a healthy week always contains one success, and a
>   missed Thursday alarms at the next 00:00 UTC.
> - **The missing-data note above is half right.** Live data shows `ExecutionsSucceeded`
>   publishes a real `0` on a day when a run *failed*, and **no datapoint** on a day when
>   nothing ran. `breaching` is still correct — it is the second case (a silently dead
>   pipeline) that would otherwise be unalarmable.
> - **Alarm 5 needed two resources, not one.** The Glue job uses `startJobRun.**sync**`, so a
>   failed integration really does mean a failed job run. The crawlers use
>   `aws-sdk:glue:startCrawler`, which has **no `.sync` variant** — the integration succeeds
>   the instant the crawler starts, so a crawl that starts and then fails is invisible while
>   the run proceeds to build gold from a stale catalog. Covered by an EventBridge rule on
>   `Glue Crawler State Change` / `state: Failed`. A Logs metric filter over
>   `/aws-glue/crawlers` was rejected: the group is account-wide, **another project writes to
>   it**, filters cannot be scoped to a stream, and the crawler name is absent from
>   individual error lines.
> - **⚠️ The alerts topic has ZERO subscribers** (`alert_email` defaults to `""`), so these
>   alarms currently notify nobody. **PR-028 should be pulled forward** or `alert_email` set
>   in tfvars at apply time.
> - Adding the EventBridge → SNS target **replaces the topic's default policy**; the module
>   reproduces the default account-owner statement alongside the new grant.
> - Also noticed, out of scope: because `startCrawler` does not wait, the gold CTAS can begin
>   *before* the crawlers finish, not just when they fail. Measured on the 2026-07-30 run,
>   **2 of the 7 CTAS started 53 s before the catalog was written**. PR-025's alarms do NOT
>   cover this — every crawl *succeeds*; the pipeline is green and the data is wrong. Filed
>   as **PR-026.1** with the full timeline.
> - Runbook: `docs/runbooks/PR-025-alarms.md`.

## PR-026 — Scraper response-code custom metric
**Prompt:**
```
In src/loteria/extractor/scraping.py, after each fetch_via_proxy call, emit a CloudWatch custom metric "ScraperHttpStatus" with dimension StatusCode=<code>. Use boto3 cloudwatch.put_metric_data with a 1-count value.
Emit the status BEFORE raising on non-200, so a failed proxy call (401/402/429 etc.) still produces a metric data point to alarm on.
Update the dashboard from PR-024 to include this metric.
Update IAM in etl-lambda module to allow cloudwatch:PutMetricData.

NOTE: this metric is what PR-025's ScrapeDo_Failed alarm watches. Rationale: scrape.do is a third-party proxy used on the FREE TIER — there is no guarantee how long it stays free. When the free plan lapses or the quota is exceeded, the proxy returns auth/quota/rate-limit codes (401/402/429) and the weekly scrape silently degrades to "Lambda error." A scrape.do-specific alarm gives an early, unambiguous heads-up (e.g. "start paying / swap proxy") instead of a generic failure.
```

> **Notes from executing it:**
> - **Two metrics, not one.** A CloudWatch alarm watches exactly one metric with one
>   dimension set, so `ScraperHttpStatus{StatusCode}` alone cannot express "alarm on any
>   non-200" without enumerating codes in advance. A dimensionless companion metric
>   **`ScraperHttpErrors`** (emitted only on non-200) is what PR-025 should alarm on, with a
>   plain `>= 1` threshold. The dashboard widget uses `SEARCH()` so new codes appear with no
>   Terraform change.
> - **`cloudwatch:PutMetricData` supports no resource-level permissions.** Scope it with the
>   `cloudwatch:namespace` condition key instead of leaving `Resource = "*"` bare.
> - **The namespace is declared twice** (Terraform `metrics_namespace` + Python
>   `loteria.common.metrics.NAMESPACE`) and a mismatch fails *silently* — every publish is
>   denied and swallowed. Keep them equal.
> - **This does NOT catch the Cloudflare waiting room**, which returns HTTP **200** with a
>   queue page — the actual cause of the 2026-07-19/20 failures. It catches scrape.do's own
>   401/402/429/5xx. Waiting-room detection needs content inspection: PR-031.
> - Runbook: `docs/runbooks/PR-026-scraper-metric.md`.

## PR-026.1 — Fix the race between `startCrawler` and the gold CTAS

**Why this is not "PR-041":** it is a **correctness defect**, not deferred scope. Found while
writing PR-025's crawler alarm; numbered `.1` so it sits next to the PR that found it and
gets picked up before more gold tables are added.

### What is happening

The state machine starts the two silver crawlers with
`arn:aws:states:::aws-sdk:glue:startCrawler`. **There is no `.sync` variant of that
integration**, so Step Functions fires the call and moves to the next state immediately — it
does not wait for the crawl to finish. The very next states are `PrepGold` → `BuildGold`,
which run the 7 gold CTAS.

So the CTAS queries race the crawlers. **Whoever wins decides whether gold sees this week's
data.**

This matters because the silver tables are partitioned by **`(year, sorteo)`** — verified
live, 109 partitions each. Every weekly run therefore creates a **brand-new partition**, and
a new partition is invisible to Athena until a crawler registers it in the Glue catalog.
This is not the usual "new files inside an existing partition" case, which Athena would pick
up on its own.

### Measured on the 2026-07-30 run (the last successful one)

| Time (UTC-3) | Event |
|---|---|
| 15:01:48.9 | `RunSorteosCrawler` — the *call* returns, SFN moves on |
| **15:02:02.2** | **first 2 `RunCTAS` start** (13 s later) |
| 15:02:09 | the sorteos crawl actually begins scanning |
| 15:02:43 | "Classification complete, writing results to database" |
| **15:02:55** | **"Finished writing to Catalog"** — the catalog is now current |
| 15:02:57 → 15:04:03 | the remaining 5 CTAS start |
| 15:06:34 | crawler reaches READY (3m39s of teardown *after* the catalog write) |

**Two of the seven CTAS ran 53 seconds before the catalog was updated.** The other five were
fine. Which two lose the race depends on `Map` scheduling (`MaxConcurrency = 3`), so **the
affected gold table is not deterministic** — a different table can be stale each week.

### Why nothing looks broken today

Checked live: `gold_draw_summary` has 109 rows, `silver_sorteos_sorteos` has 109 distinct
sorteos, and `MAX(numero_sorteo)` is **3130 in both**. No drift right now.

That is luck, not health. The 2026-07-30 run introduced **no new sorteo** (3130 was already
in the catalog from the 2026-07-26 run), so the two CTAS that read a stale catalog read a
*correct* stale catalog. The damage only materializes on a run that actually ingests a new
sorteo — i.e. a normal week — and then it is silent: no failure, no alarm, just a gold table
missing the newest draw until the following week's rebuild papers over it.

**PR-025 does not fix this.** Its crawler alarms fire when a crawl *fails*; here every crawl
succeeds. The pipeline is green and the data is wrong.

**Prompt:**
```
Fix the ordering in terraform/modules/orchestration/main.tf so the gold CTAS cannot start
before both silver crawlers have finished writing to the Glue catalog.

Preferred approach — poll for completion (there is no .sync integration to switch to):
1. After RunSorteosCrawler, add a Wait state (~30 s) then a Task using
   arn:aws:states:::aws-sdk:glue:getCrawler for each crawler.
2. A Choice state loops back to the Wait while Crawler.State != "READY", and proceeds to
   PrepGold only when both are READY.
3. Add a total-wait guard so a hung crawler fails the execution instead of looping forever
   (a counter incremented in a Pass state, or a Wait/Choice budget of ~15 min — the observed
   worst case is 4m26s wall clock, of which only the first ~46 s is catalog work).
4. The SFN IAM policy needs glue:GetCrawler on both silver crawlers. Narrow it the way
   PR-009 narrowed StartCrawler — do not reintroduce a wildcard.

Consider instead (and document the choice): run the two crawlers in a Parallel state, since
today premios and sorteos are started back-to-back and both must finish anyway.

Verification:
- terraform plan shows ONLY the state machine + the SFN IAM policy changing.
- Trigger one execution and confirm from the execution history that every RunCTAS
  timestamp is AFTER the "Finished writing to Catalog" line for BOTH crawlers in
  /aws-glue/crawlers.
- Confirm gold row counts match silver on a run that ingests a new sorteo:
  SELECT MAX(numero_sorteo) FROM gold_draw_summary  -- must equal silver's MAX

Out of scope: retries/Catch on the other states, the crawler-failure alarms (PR-025 owns
those), and any change to the CTAS SQL itself.
```

**Acceptance:** No CTAS can observe a catalog older than the run that triggered it. On a run
that ingests a new sorteo, `MAX(numero_sorteo)` in gold equals silver's in the same run.

> **Notes from executing it (2026-08-09):**
> - **Took the `Parallel` option.** Both crawlers must finish before gold can build, and
>   `READY` lags the catalog write by ~3.5 min of crawler teardown, so serial polling would
>   have paid that twice for nothing.
> - **Polling for `State == READY` alone would have been a NEW bug.** `READY` is also what a
>   crawler reports in the gap between `StartCrawler` returning and the control plane
>   flipping it to `RUNNING` — the first poll could read that stale value and declare a crawl
>   finished before it began. Each branch now captures `LastCrawl.MessagePrefix` (the crawl's
>   own UUID) *before* starting, and completion requires that prefix to have **changed**.
>   A crawler that has never run has no `LastCrawl` block at all, so that case gets its own
>   Choice rule and every comparison is `IsPresent`-guarded.
> - **Step 4 of the prompt was already done.** PR-009 granted `glue:GetCrawler` alongside
>   `glue:StartCrawler`, already narrowed to the two silver crawler ARNs — verified against
>   the live `sfn-lottery-policy-prod` v7, not the code. This PR needs **no IAM change**;
>   the plan is exactly `1 to change`.
> - **Added beyond the prompt, deliberately:** a `Verify` Choice fails the execution when
>   `LastCrawl.Status != SUCCEEDED`. A failed crawl leaves the catalog exactly as stale as no
>   crawl, so the acceptance criterion is not met without it. This *changes* behaviour — a
>   failed crawl used to let the pipeline finish green — and it gives the run an owner
>   (PR-025's `SFN_ExecutionFailed`).
> - **`aws stepfunctions validate-state-machine-definition` is the cheap gate here.** The
>   definition is generated by a `for` expression over a map, so a `Choice`/intrinsic typo
>   would otherwise surface five minutes into a weekly run. Result `OK`, 0 diagnostics.
> - **✅ VERIFIED IN PROD 2026-08-09** — execution `pr0261-verify-1786291620`, `SUCCEEDED` in
>   4m59s. Last catalog write **16:08:42.100 UTC**, first `RunCTAS` **16:09:04.466 UTC** →
>   **+22.4 s margin**, against **−53 s** on the pre-fix 2026-07-30 run. A ~75 s swing; all 7
>   CTAS started after both crawlers had written. Each branch polled **twice** (a `1` would
>   have meant the first poll read a stale `READY`), and both reached `CrawlSucceeded`.
>   Data check: `gold_draw_summary` and `silver_sorteos_sorteos` both `MAX(numero_sorteo)`
>   **3132**, 111 rows vs 111 sorteos. This check is *conclusive* now, unlike before the fix —
>   the counts moved 109/3130 → 111/3132, so new sorteos really were catalogued.
> - **Latency was cheaper than estimated:** predicted +4–5 min, measured **+40 s** (4m59s vs a
>   ~4m20s baseline). `Parallel` overlaps the two waits and both crawlers hit `READY` within
>   two poll intervals.
> - **Renumbered `.5` → `.1` on 2026-08-09** at the owner's request (purely cosmetic — the
>   only code touched was HCL comments, and `terraform plan` stayed `No changes`).
> - Runbook: `docs/runbooks/PR-026.1-crawler-race.md`.

---

## PR-027 — (Optional) S3 object-count emitter
**Prompt:**
```
Tiny scheduled Lambda (EventBridge cron every 1 hour) that runs:
  for prefix in ["raw/", "silver/", "gold/"]:
    count = sum(1 for _ in s3.list_objects_v2_paginated)
    cloudwatch.put_metric_data(MetricName="ObjectCount", Dimensions=[{"Layer": prefix}], Value=count)
Add to terraform/modules/observability/ as a sub-module or new aws_lambda_function. Skip if the dashboard from PR-024 already feels rich enough.
```

> **Notes from executing it (2026-08-09): built, not skipped.** The reason is worth keeping:
> every other widget on the PR-024 dashboard measures an **execution**; none measures the
> **asset**. A run can go green end to end and add nothing — the extractor re-scrapes a page
> it already has, the transformer rewrites the same partition, `AWS/States` reports success
> and PR-025's alarms stay quiet. A flat `raw/` line beside green executions is the only
> place that shows. Same category as PR-026.1: green pipeline, wrong data.
> - **S3's free metrics can't do this.** `AWS/S3` `NumberOfObjects` / `BucketSizeBytes` are
>   per-**bucket** only. All three medallion layers share one bucket, so a custom emitter is
>   the only way to get the per-prefix breakdown.
> - **Emits `BytesStored` too** (beyond the prompt). It comes back in the same
>   `ListObjectsV2` response as the count — no extra API call — and an object *existing* is
>   not an object *having data*: a truncated scrape still increments `ObjectCount`. Cost of
>   the extra series is 3 metrics × $0.30/mo.
> - **The dimension format in the prompt is wrong.** boto3 wants
>   `[{"Name": "Layer", "Value": ...}]`, not `[{"Layer": ...}]`.
> - **`aws_lambda_permission` is the silent-failure trap.** EventBridge invokes Lambda by
>   *resource policy*, not by execution role. Without it the rule fires forever, nothing runs,
>   and the only evidence is the rule's `FailedInvocations` metric.
> - **No `s3:GetObject` in the role.** Counting and sizing come entirely from the list
>   response, so the emitter can see that objects exist and how big they are and can never
>   read them. `s3:ListBucket` goes on the *bucket* ARN — the `bucket/*` form grants nothing.
> - Gated by `enable_object_count_emitter` (default true) so "optional" is real without
>   deleting code. `processed/` excluded — frozen legacy prefix from PR-012.
> - **Plan surprise worth remembering: the gold-purge Lambda shows up as a change in this
>   PR, and it is not a mistake.** PR-023 gave `module.orchestration` a
>   `depends_on = [module.iam]`; a module whose `depends_on` target has pending changes
>   **cannot have its data sources read at plan time**. PR-027 adds 4 resources to
>   `module.iam`, so `data.archive_file.gold_purge` is deferred → `source_code_hash` unknown
>   → a planned in-place update that re-uploads byte-identical code (local zip hash and the
>   deployed `CodeSha256` both `rWrVT00c…`). One-time, and it will recur for **any** future
>   PR that adds a resource to `module.iam`.
> - Runbook: `docs/runbooks/PR-027-object-count.md`.

## PR-028 — Wire SNS email subscription via tfvars
**Prompt:**
```
Add `alert_email = "you@example.com"` to terraform.tfvars.example as a PLACEHOLDER.
Never commit a real address: terraform.tfvars.example is public, terraform.tfvars is gitignored — the owner's real address goes only in the latter.
Document that the owner must confirm the SNS email subscription in their inbox after first apply.
```

> **Notes from executing it (2026-08-09):**
> - **This is the PR that makes PR-025 real.** Those six alarms had been sitting on a topic
>   with **zero subscribers** — correct alarms, silent inbox. Verified live before the change:
>   `list-subscriptions-by-topic` returned an empty list.
> - **`terraform apply` cannot finish this.** AWS emails a confirmation link and a human must
>   click it; there is no API to confirm on the subscriber's behalf, by design. Terraform
>   reports the subscription **created either way**, so a green apply is *not* proof that
>   alerts will arrive. Unconfirmed subscriptions carry the literal ARN
>   `PendingConfirmation`. The link expires after 3 days (`apply -replace` resends), the
>   subject line is generic, and it often lands in spam.
> - **`confirmation_timeout_in_minutes = 1` is not the click deadline** — it is only how long
>   Terraform waits before giving up on observing confirmation.
> - **Confirming the subscription only tests the last hop.** It proves SNS reaches the inbox,
>   not that an *alarm* reaches SNS (which also needs the topic policy and `alarm_actions`).
>   `aws cloudwatch set-alarm-state --state-value ALARM` drives a real transition through the
>   whole chain and is safe — CloudWatch overwrites the forced state at the next evaluation.
>   Expect **one** email, not two: `ok_actions` is deliberately unset.
> - **Added beyond the prompt:** a plan-time regex validation on `alert_email`. SNS accepts
>   almost any string as an email endpoint and simply never delivers, so a typo would
>   silently recreate the very "alarms notify nobody" state this PR removes.
> - The `.example` suffix is what keeps the template out of `.gitignore`'s `*.tfvars` glob —
>   verified both directions with `git check-ignore`, plus a `git grep` for the real address
>   across tracked files.
> - Runbook: `docs/runbooks/PR-028-alert-email.md`.

---

# Phase 5 — QA / Testing (the showcase)

## PR-029 — pytest skeleton + first parser unit tests
**Prompt:**
```
1. Create tests/ with tests/unit/, tests/integration/, tests/fixtures/.
2. Capture 3 real .txt files from raw/ and store under tests/fixtures/sorteos/, anonymizing
   ONLY the vendor-name segment: `VENDIDO POR <name>, DE <ciudad>[, <depto>]` becomes
   `VENDIDO POR VENDOR_001, DE <ciudad>[, <depto>]`.
   ⚠️ Do NOT replace the whole `vendido_por` field. It is comma-delimited and
   `split_vendido_por_column` splits on commas, so collapsing it to a bare `VENDOR_001`
   destroys ciudad/departamento and makes test 3's "yields vendedor/ciudad/departamento;
   handles ciudad-only rows" impossible to write. Ciudad and departamento are public
   geography, not personal data — keep them verbatim. Keep `NO VENDIDO` lines untouched.
   Use a stable name→id map so the same person is the same VENDOR_NNN in every fixture.
3. Write tests/unit/test_parser.py covering:
   - split_header_body: HEADER/BODY found correctly; ValueError on malformed input
   - process_header: every field extracted; correct types; raises on missing fields
   - process_body: count of premios matches expected; "NO VENDIDO" sets vendido_por correctly
   - split_vendido_por_column: yields vendedor/ciudad/departamento; handles ciudad-only rows
4. Configure pytest in pyproject.toml: --cov=src/loteria --cov-fail-under=70 (will ratchet up).
5. Wire `make test` to `pytest -v`.
```

> **Notes from executing it (2026-08-09):**
> - **`--cov-fail-under=70` is NOT reachable here, and shipping it would break the gate on
>   the PR that introduces it.** `src/loteria` is 502 statements; PR-029 covers `parser.py`
>   (59) = **11.8%**, PR-030 adds `transformer.py` (111) = **33.9%**, and PR-031's scraper
>   test is skipped by default so it adds 0. A gate that fails from birth just teaches
>   everyone to run `pytest --no-cov`. Set to **11** and raised in the same PR that adds the
>   tests (PR-030 → 33, PR-035 → 85, which already says "add tests as needed"). Coverage is
>   measured over **all** of `src/loteria`, not scoped to the tested modules — a flattering
>   number that hides the untested majority is the wrong default for a data-quality repo.
> - **The anonymizer is committed** (`scripts/anonymize_fixture.py`) rather than run ad hoc,
>   with a `--check` mode that exits non-zero if a fixture still holds a real name. Run all
>   files in ONE invocation: the shared name→id map is what keeps a person mapped to the same
>   `VENDOR_NNN` across fixtures.
> - **The vendor field holds more than names.** Real example in the capture:
>   `PERSONA CON DISCAPACIDAD VISUAL <nombre>` — disability status. Replacing the whole
>   pre-comma segment removes it; matching "name-shaped" substrings would not have. Worth
>   knowing that `raw/` and `silver_premios_premios.vendedor` are more sensitive than the
>   column name suggests.
> - **Fixture choice matters more than "3 files".** The extraordinario is in the set because
>   extraordinarios use a **separate numbering sequence** (411/412/413, not 3xxx) and contain
>   **zero** `NO VENDIDO` lines — two assumptions that are otherwise easy to bake in.
> - 45 tests, `parser.py` at **100%** coverage.

## PR-030 — Transformer unit tests with moto
**Prompt:**
```
Write tests/unit/test_transformer.py:
- Use moto to stand up fake partitioned + simple buckets.
  ⚠️ Use `from moto import mock_aws`, NOT `mock_s3`. `mock_s3` is the moto v4 API and was
  REMOVED in moto 5 (one `mock_aws` now covers every service). `moto` is unpinned in
  pyproject, so pip installs 5.x and `from moto import mock_s3` raises ImportError.
- Upload a fixture .txt under raw/year=2024/sorteo=3046/.
- Run transformer.transform(...) against the fake buckets.
- Assert: silver parquet files appear at the expected key, schema matches the canonical one, dtypes correct, year partition derived correctly.
- Add an edge-case test for the "Invalid fecha_sorteo" path (it should raise ValueError).
```

> **Notes from executing it (2026-08-09):** 23 tests, `transformer.py` at **86%**, suite
> total **42.23%** (the 33.9% estimate was low — moto exercises `s3_utils` to 73% and
> `aws_secrets` to 45% as a side effect of running the transform for real).
> - **Two import-time landmines had to be defused before the module could even load**, and
>   both are properties of how it runs in Glue: `from awsglue.utils import getResolvedOptions`
>   at module scope (awsglue is not on PyPI — stubbed in `tests/conftest.py`), and
>   `buckets = get_secrets()` at module scope, a Secrets Manager call that fires on **import**
>   (the same fact that forced `scripts/glue_zip_main.py` to bridge `--LOTERIA_SECRET_NAME`
>   into the env before importing the transformer).
> - **`transform()` reads from its `bucket_name` argument but WRITES to module globals**
>   (`partitioned_bucket` / `simple_bucket`). They agree in production because `main()` sets
>   both, but a caller passing only `bucket_name` would read one bucket and write to another.
>   Latent smell, not fixed here — out of scope for a test PR.
> - **Schema is asserted at the PARQUET level, not the pandas level.** Parquet is the real
>   contract (the crawler infers the Athena table from it, and the gold CTAS read that table),
>   and it is the only version-stable choice: local pandas 3.x gives an un-cast string column
>   the new `str` dtype while Glue's Python Shell 3.9 pandas gives `object`. Both write a
>   Parquet string. Numeric/timestamp types are still pinned exactly, since the code casts
>   them explicitly and int32-vs-int64 is visible to Athena.
> - **Found while writing the schema test: `tipo_sorteo` is the one string column in
>   `sorteos_df` that never passes through `_to_string()`** — its type is left to pandas
>   inference. Harmless today, but it means a pandas upgrade inside Glue could silently change
>   the Silver Parquet schema. Worth an explicit cast in a future PR.
> - **The strongest test is `test_year_comes_from_fecha_sorteo_not_from_the_raw_path`.** The
>   Silver year partition is derived from the parsed `fecha_sorteo`, not from the `year=` in
>   the raw key. In every real file those agree, so a naive test would pass on a coincidence;
>   filing the fixture under `year=1999` and asserting it lands in `year=2024` proves the
>   derivation.

## PR-031 — Scraper contract test (canary)
**Prompt:**
```
Write tests/integration/test_scraper_contract.py:
- Marks: pytest.mark.integration; skip by default unless env var RUN_LIVE_SCRAPER=1.
- Hits the real loteria.org.gt via scrape.do (token from env), parses the awards page, asserts:
  * at least one `<a href="...id=...">` exists
  * the heading h2 matches the SORTEO regex
  * div.heading_s1.text-center exists
  * div.card-body div.row has at least 3 children
- This test is the canary that catches the site changing layout *before* the weekly run does.

Document a GitHub Actions cron workflow that runs ONLY this test every Sunday at 18:00 UTC (one day before the Monday cron). If it fails, the owner gets a notification before prod fails.
```

> **Notes from executing it (2026-08-09):** 7 tests, **all passing against the live site**.
> - **The cron is WEDNESDAY 18:00 UTC, not Sunday.** The prompt's "one day before the Monday
>   cron" is stale: PR-022 moved the pipeline to **Thursday**. A Sunday run would land in the
>   exact post-Saturday Cloudflare waiting-room window that the Thursday move exists to dodge,
>   and would mostly report skips. Wednesday keeps the 24h lead time the prompt actually
>   wanted.
> - **The workflow is CREATED here, not just documented** (`.github/workflows/scraper-canary.yml`).
>   A documented-but-absent canary protects nothing. **PR-034 must not recreate it** — its
>   prompt also lists `scraper-canary.yml`; that half is already done.
> - **The canary does NOT import `loteria.extractor.scraping`.** That module calls
>   `get_secrets()` at import time, so importing it would drag Secrets Manager (and AWS
>   credentials) into a workflow that otherwise needs none. The token comes from
>   `SCRAPE_DO_TOKEN` instead. The cost is that the selectors are written twice, so an
>   **offline** test asserts every locator literal still appears in `scraping.py` — otherwise
>   a scraper edit could leave the canary watching a selector nothing uses.
> - **⚠️ pytest gotcha, cost an hour: `item.keywords` contains the test's PATH components.**
>   PR-029's conftest skipped on `"integration" in item.keywords`, which matches *every* test
>   under `tests/integration/` regardless of marker — so the offline guard above was silently
>   skipped. Invisible until this PR put the first file in that directory. Fixed to
>   `item.get_closest_marker("integration")`.
> - **Three failure modes are distinguished**, because they need different responses: a
>   Cloudflare waiting room (HTTP **200** with a queue page — invisible to PR-026's status
>   metric) **skips**; a scrape.do 401/402/429 **fails** naming the proxy quota; a real
>   selector mismatch **fails** naming the selector.
> - **Added beyond the prompt:** the prompt's `len(rows) >= 3` only proves three rows exist,
>   not that the third still holds the prizes — the extractor indexes `result_divs[2]`
>   positionally, so inserting one row above it would silently write the wrong text to `raw/`.
>   A companion test asserts row 3 contains ≥10 prize-shaped lines.
> - The workflow reuses one open issue instead of filing a duplicate every week, and fails
>   loudly if `SCRAPE_DO_TOKEN` is unset (a canary that silently skips everything is worse
>   than none). **The owner must add that repository secret.**
>
> **⚠️ FOLLOW-UP FIX 2026-08-15 (branch `fix/canary-token-leak`, non-roadmap) — this PR could
> have published the scrape.do token.** scrape.do authenticates by **query parameter**, so
> the token sits in every request URL, and every `requests` exception embeds that URL. Chain:
> a ConnectionError prints the token in the traceback → `tee canary.log` writes it to disk
> **raw** (GitHub masks its log *stream*, not a file the job writes) → the failure handler
> builds the issue body from that file → **the repo is public**. Observed for real: a local
> run on 2026-08-15 failed with the live token in full in the traceback. Fixed in two layers
> — `fetch()` now catches `requests.RequestException` and re-raises scrubbed (`from None` is
> load-bearing: without it Python still prints the original under "During handling of the
> above exception"), and the workflow scrubs `canary.log` before anything reads it. Seven
> unmarked (offline, always-run) tests guard it, including one that renders the full
> traceback the way pytest would and asserts the token is absent. **Also fixed here:** the
> issue step's `steps.canary.outcome == 'failure'` condition never fired when the *token
> guard* failed (different step, no id), which is why three weeks of red canary runs filed
> no issue at all. Now plain `failure()`.
>
> **The ordering was botched, and that is the part worth remembering.** This PR's own
> description said *"merge this before adding the `SCRAPE_DO_TOKEN` repository secret"* — and
> on 2026-08-27 the secret was added first, during the PR-031.1 restore, while this fix sat
> open and conflicting. That left a real exposure window: the repo is public, the canary was
> now armed, and any connection failure would have posted the token into an issue. Nothing
> fired (the next scheduled run was 2026-09-02 and no manual dispatch happened), so it closed
> clean — but only by luck of the calendar. **A security fix that gates another action has to
> be merged when that action happens, not filed next to it**; an open PR is not a guardrail.
> The rebase over PR-031.1 also had to keep `timeout=60`, not the 45 s this branch was written
> against — lowering it would have quietly reverted the change PR-031.1 exists for.
>
> **⚠️ FOLLOW-UP FIX 2026-09-09 (branch `fix/canary-coverage-addopts`, non-roadmap) — the
> canary had never once run its tests.** The first issue it ever filed (GH #43, the run on
> `d791c83`) did not report a site change: it reported `pytest: error: unrecognized
> arguments: --cov=src/loteria --cov-report=term-missing --cov-fail-under=56 --no-cov`. The
> job installs `pytest requests beautifulsoup4` and no pytest-cov, so **every one of those
> flags, `--no-cov` included, is unknown to it** — `--no-cov` is a pytest-cov option, and
> disabling a plugin you never installed is not a thing pytest can parse. It exited at
> argument parsing, before collection, in 9 seconds. That has been true since PR-031 first
> shipped the workflow (the `--cov` addopts predate it, from PR-029); it stayed invisible
> because the *previous* bug swallowed the alert — three weeks of red runs filed no issue,
> and the token-leak fix above is what finally let the real error speak.
>
> Fixed by replacing `--no-cov` with `-o addopts="-ra --strict-markers"`, which **overwrites**
> the pyproject line instead of trying to opt out of one of its flags. Chosen over adding
> pytest-cov to the install step because it also insulates the canary from whatever the repo
> bolts onto `addopts` next. Verified by running the exact command with the plugin blocked
> (`-p no:cov`): 8 passed, 6 skipped, exit 0.
>
> **The lesson is about layered alerting, not about pytest.** Two independent defects sat on
> the same path — a broken alert condition in front of a broken command — and the outer one
> made the inner one unobservable for a month. A monitor is not verified until you have seen
> it produce a *green* run, not merely a red one; "no issue filed" was indistinguishable from
> "nothing wrong". Neither bug could reach the pipeline (the canary is read-only, and the
> Thursday runs kept working), but the lead time it exists to buy was zero the whole time.

## PR-031.1 — Restore the scraper (unplanned; outage 2026-08-20 → 2026-08-27)

Not a roadmap item — an incident fix, filed like PR-026.1 was. Runbook:
`docs/runbooks/PR-031.1-scraper-restore.md`.

### ✅ RESOLVED 2026-08-27 — applied, merged, and the missing sorteos recovered

[PR #42](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/42)
is applied to AWS and merged. The outage ran 2026-08-20 → 2026-08-27 (two failed weekly
runs). Verified live after the apply:

| Check | Result |
|---|---|
| `extractor_lambda` `CodeSha256` | `dTb0IUUM9hoRGFr66sfOGwKp8onAb/w0IXuor+KadnA=`, matches the built zip |
| Lambda env | `SCRAPE_GEO_CODE=GT`, `SCRAPE_RENDER=true`, `SCRAPE_SUPER=true`, `SCRAPE_TIMEOUT=60` — none existed before |
| Layer | `loteria-deps-prod:3` |
| `RunExtractorLambda` | the 7-error `Retry` block is live in the deployed ASL |
| `raw/sorteo_3133.txt` | 1061 lines, **896 prize lines** (historical 3132: 1060 / 895) |
| `raw/sorteo_414.txt` | 1769 lines, **1608 prize lines** (Extraordinario, larger by nature) |

Both raw files were checked for the silent failure this PR fixes — they carry real prizes,
not the legal boilerplate the old positional selector would have written.

**The data was stale, never corrupt.** Both failed runs died at step 1, so Glue, the
crawlers and the gold CTAS never executed and no partial writes existed to clean up.

#### The apply did not match the prediction — and the prediction was the wrong shape

The runbook promised `0 add, 2 change, 0 destroy`. The real plan, taken against the live
account after `make build`, was **`1 add, 5 change, 1 destroy`**; the apply reported
`1 added, 4 changed, 1 destroyed` (one planned update resolved to a no-op at apply time).
PR-031.1's own share *is* exactly 2 — `extractor_lambda` and `pipeline_state_machine`. The
rest is the artifact churn this repo produces on every build:

| Extra change | Why |
|---|---|
| `aws_lambda_layer_version` (add + destroy) | pip rebuilds the layer, the hash moves, `create_before_destroy` makes a new version and retires the old one |
| `aws_s3_object.lambda_layer` / `.lambda_package` | the rebuilt zips |
| `aws_lambda_function.gold_purge` | the `data.archive_file` phantom from the deferred module data-source read |

**Lesson, and it is the same one as PR-019: predict plans against the live account, not
against the PR in isolation.** A prediction that counts only the PR's own resources will be
wrong every time `make build` runs, and an owner who trusts it has no way to tell expected
churn from a real surprise.

#### `SCRAPE_DO_TOKEN` lives in two unrelated places — do not conflate them

This cost time during the apply. There are two tokens with the same purpose and no
relationship:

- **AWS Secrets Manager `lottery_secret_prod_2`** already held `scrape_do_token` and always
  had; the extractor reads it at import time. **Nothing was ever owed here.**
- **The GitHub Actions repository secret `SCRAPE_DO_TOKEN`** is what PR-031 left open and
  what the `scraper-canary` workflow reads. It was set on 2026-08-27.

The name has to match `secrets.SCRAPE_DO_TOKEN` in `.github/workflows/scraper-canary.yml`
**exactly** — GitHub resolves an undefined secret to the empty string, so a near-miss name
reproduces the original bug (a canary that fails at the token guard) with no hint that the
secret exists at all. `gh secret list` / `gh secret set` return `403` with the owner's PAT;
this is a web-UI operation.

### Owner actions — done 2026-08-27, except the standing one

1. ~~**Apply PR #42.**~~ Done. `make build` first (mandatory — `filemd5`/`filebase64sha256`
   read the zips at plan time, so a stale artifact fails the *plan*), then
   `terraform plan -out=tfplan && terraform apply tfplan`. See the plan-shape note above.
   ⚠️ The warning that made this step worth writing still stands for every future PR:
   **merging is not applying, and the zip re-upload is the step that gets skipped** — the
   PR-019 trap, where the extractor ran three PRs behind for weeks.
2. ~~**Recover the two missing sorteos.**~~ Done — both landed and were checked for prize
   content. **`lottery_number` in the invoke payload is the site's internal `id`, not the
   sorteo number**, because `extract_lottery_data` matches on `href*="id={lottery_number}"`.
   Passing `3133` finds nothing and raises "No se pudo encontrar el enlace al sorteo". The
   ids are only discoverable from the listing page:

   | Sorteo | site `id` |
   |---|---|
   | Ordinario 3133 (22/08/2026) | `291` |
   | Extraordinario 414 (15/08/2026) | `288` |
   | Ordinario 3132 | `290` |

   ```bash
   aws lambda invoke --function-name lottery-extractor-prod \
     --cli-binary-format raw-in-base64-out --payload '{"lottery_number": 291}' /dev/stdout
   ```
   Worth fixing properly one day: the payload field is named `lottery_number` but holds a
   site id, which is exactly the kind of naming that makes a recovery take three attempts
   under pressure.
3. ~~**Set the `SCRAPE_DO_TOKEN` repository secret.**~~ Done — open since PR-031, during
   which the canary failed every week from 2026-08-09 (runs 12/19/26-ago, each ~13 s, dying
   at the token guard without ever reaching the site). It held the test that would have
   caught the redesign a day early. See the two-tokens warning above.
4. **Watch the credit burn** for a month — *still open.* See the cost note below; the budget
   is no longer negligible. Recovering this outage alone cost ~150 credits (2 invocations at
   50 + one listing fetch during diagnosis).

### One run does not equal one sorteo

The transformer scans **all** of `raw/` and skips whatever is already in Silver
(`transformer.py:92-117`), so a single Step Functions execution picks up every recovered
sorteo at once — 3133 and 414 were processed in the same run. The extractor step ahead of it
is a safe no-op when the latest sorteo already exists: `check_if_sorteo_exists` makes
`extract_lottery_data` return `None`, the handler still returns `{"status": "ok"}`, and the
state machine moves on. It does still spend 50 credits re-fetching to find that out.

### The proxy profile — all six subsets fail, keep all three parameters

| Attempt | Result |
|---|---|
| `geoCode` plain: AR, BR, CL, CR, US, MX | `ROTATION_FAILED` |
| `super=true` + GT / MX / CO / SV | `ROTATION_FAILED` |
| `render=true` alone | `ROTATION_FAILED` |
| `render` + `geoCode=MX` | `ROTATION_FAILED` |
| `render` + `geoCode=GT`, no `super` | `ROTATION_FAILED` |
| `render` + `super`, no `geoCode` | `ROTATION_FAILED` |
| **`render` + `super` + `geoCode=GT`** | **HTTP 200 in ~5-6 s** |

scrape.do's country pools: datacenter covers a limited set (the published list omits `MX`, which nonetheless works — the list is incomplete); residential (`super=true`) covers 22 LATAM countries including `GT`. Guatemala is **residential-only**, which is why `super` and `geoCode` cannot be separated here. Verified by fetching `ipinfo.io/json` through the proxy: `geoCode=GT&super=true` really does exit via `AS52362`, a Guatemalan ISP.

> **Two independent failures, and the roadmap should record both because each one has a
> lesson.**
>
> - **The proxy profile died.** loteria.org.gt tightened Cloudflare; every request came back
>   `502 ROTATION_FAILED / "cannot connect target url"` after ~57 s. That error reads like an
>   unreachable host but is scrape.do's plain HTTP client failing a browser check — the tell
>   is that a direct `curl` gets a **fast 403 block page** while the proxy gets **no response
>   at all**. The fix is `render=true` + `super=true` + `geoCode=GT` **together**; all six
>   proper subsets were tested live and every one still failed. So geo-targeting does matter
>   (GT is residential-only), just never on its own.
> - **The site moved the prize list, and the old locator failed SILENTLY.** The extractor read
>   `div.card-body div.row` at index `[2]`; the redesigned page still has exactly three rows
>   and index 2 now holds legal boilerplate. `len(rows) >= 3` passed, the run would have gone
>   green, and `raw/` would have gained a prize-less file. **PR-031's canary predicted this
>   exact failure and added the companion test for it** (see the note above) — the canary was
>   right, but it had been red since 2026-08-09 on the unset `SCRAPE_DO_TOKEN` secret, so
>   nobody read it. *A canary nobody can hear is not a canary.*
>
> **The alarm stayed green through all of it.** `record_scraper_status()` needs a response
> object, so a `ReadTimeout` emitted no datapoint and `ScrapeDo_Failed` sat in OK for two
> weeks. `ScraperHttpStatus` had never recorded any dimension value but `200`. New
> `record_scraper_no_response()` emits `StatusCode=NoResponse` onto the series the alarm
> already watches — no alarm or dashboard change needed.
>
> **The 25 s timeout was hiding the evidence:** it sat *below* scrape.do's own ~57 s give-up,
> so prod only ever saw a local `ReadTimeout` and never the real 502. Raised to 60 s.
> Generalizable: **a client timeout shorter than the upstream's own timeout converts a
> diagnosable error into an anonymous one.**
>
> **Cost changed by 25x** — 25 credits per successful request instead of 1, on a 1000/month
> plan, ~215/month at the current cadence (~26% of quota). Retries are therefore explicitly
> scoped to transient errors rather than `States.ALL`. Failed requests are not charged, which
> means **a full quota counter is not evidence the pipeline ran** — during the outage it read
> a pristine 1000/1000.
>
> **Deferred (filed, not built):** the detail page ships a 52 KB inline
> `premiosBusqueda = {"00068":{"monto":800,"vendidoPor":""}, …}` object — number → amount +
> vendor, already structured. Parsing that instead of the DOM would make the extractor immune
> to this whole class of redesign. Worth a PR of its own.

## PR-032 — Great Expectations suite for Silver
**Prompt:**
```
1. Initialize GX under qa/great_expectations/.
2. Datasource: pyarrow/parquet pointing at s3://<partitioned>/silver/sorteos/ and silver/premios/.
3. Expectation suite "silver_sorteos":
   - expect_column_values_to_not_be_null: numero_sorteo, fecha_sorteo, primer_premio
   - expect_column_values_to_be_between: monto >= 0 (n/a on sorteos — use on premios instead)
   - expect_column_values_to_be_unique: numero_sorteo
   - expect_column_values_to_match_strftime_format: fecha_sorteo as date
4. Expectation suite "silver_premios":
   - expect_column_values_to_not_be_null: numero_sorteo, numero_premiado, monto
   - expect_column_values_to_be_in_set: departamento in ['GUATEMALA', 'SACATEPÉQUEZ', ... full 22 deptos + None]
   - expect_column_values_to_be_between: monto >= 0
5. Add scripts/run_dq.py that runs both suites and exits non-zero on failure. Wire as `make dq`.
```

> **Notes from executing it (2026-08-15):** 20 expectations across two suites, 58 new tests,
> and a green run against the **real** Silver layer (111 sorteos / 116,757 premios).
>
> - **🚨 BLOCKER FOR PR-033, FOUND HERE: `great-expectations` 1.x requires Python ≥ 3.10, and
>   Glue Python Shell supports only 3.6 and 3.9** (PR-020's spike). PR-033's prompt — "a
>   Python Shell job that pip-installs great-expectations" — **cannot work as written**. On
>   3.9 pip silently resolves back to the GX 0.18 line, whose API is unrelated to 1.x, so it
>   would install cleanly and then fail at import. PR-033 has to pick a 3.10+ runtime
>   (Glue ETL 4.0 is 3.10, Glue 5.0 is 3.11) or move the job off Glue. Recorded in
>   `pyproject.toml` and `requirements/dq.txt` so it cannot be rediscovered the hard way.
> - **The expectations were derived from prod, then written — not the other way round.** The
>   whole Silver layer was profiled first, and every expectation was run against all 116,757
>   rows before being committed. A suite that fails on day one becomes a gate people route
>   around, which is the canary-that-always-skips failure from PR-031 wearing a new hat.
> - **The 22 departamentos carry the source's typo: the site writes `ALTA VERAPÁZ` and
>   `BAJA VERAPÁZ`**, with an accent that does not belong on "Verapaz". The value set has to
>   describe what loteria.org.gt emits, not correct Spanish — a well-meaning fix would break
>   the expectation against every real batch. There is a test whose only job is to fail if
>   someone "corrects" it. Profiling also confirmed exactly 22 distinct values and no garbage
>   from bad `vendido_por` splits.
> - **The prompt's `expect_column_values_to_match_strftime_format` is not used.** The
>   transformer already parses with `pd.to_datetime(format="%d/%m/%Y")`, so Silver holds a
>   real `datetime64` — there is no string left to match, and the expectation would compare
>   against `"2024-06-01 00:00:00"` and fail. A range expectation plus not-null covers the
>   intent, because `errors="coerce"` turns an unparseable date into `NaT`.
> - **The prompt's `None` in the departamento value set is unnecessary.** ~91% of premios rows
>   have null geography (no `VENDIDO POR` line), and GX column-map expectations skip nulls by
>   default. A test pins that behaviour, since the suite would be wrong in opposite directions
>   depending on which is true.
> - **A GX S3 datasource was rejected, despite the prompt asking for one.** Silver is one
>   Parquet file per draw, so each GX *batch* would be a single file — and `silver/sorteos`
>   files hold exactly **one row each**. `expect_column_values_to_be_unique` on
>   `numero_sorteo` — the expectation that guards the transformer's idempotency check, and the
>   most valuable one in the project — would then be trivially true in every batch and prove
>   nothing forever. Uniqueness is a property of the dataset, so the dataset is what gets
>   validated: boto3 + BytesIO into one DataFrame (also avoids `s3fs`, which drags in
>   `aiobotocore` and pins `botocore` hard).
> - **⚠️ `ExpectationSuite.add_expectation()` requires an ambient GX data context** — it
>   reaches for the global project manager to check whether the suite was already persisted,
>   and raises `DataContextRequiredError` in a fresh process. The first draft used it and
>   worked only because a context happened to exist. The suites now pass expectations to the
>   `ExpectationSuite(...)` constructor, which is context-free, so the builders are pure and
>   unit-testable. A test asserts this stays true.
> - **The committed suite JSON is normalised, because GX mints a fresh UUID for the suite and
>   for every expectation on every write.** Left alone, `--sync-suites` after a one-line
>   change rewrites all ~110 lines, which destroys the only reason to commit the file. The ids
>   are stripped after writing (GX re-mints them on read and does not rewrite the file), and a
>   test asserts the sync is idempotent. A second test asserts the committed JSON still matches
>   the Python builders, so it cannot go stale.
> - **GX is loud by default and had to be quieted for PR-033**: the tqdm "Calculating Metrics"
>   bar redraws with carriage returns, and CloudWatch retains every redraw, so one validation
>   lands as a single enormous unreadable line. It is a data-context setting
>   (`ProgressBarsConfig(globally=False)`), not an env var. Separately,
>   `logging.getLogger("great_expectations").setLevel(WARNING)` is **not enough** — GX sets
>   explicit levels on submodule loggers and an explicit child level beats an inherited one,
>   so every registered `great_expectations*` logger has to be set directly, after import.
> - **The strongest test is `TestAgainstRealTransformerOutput`.** It runs the actual
>   transformer over the anonymized fixtures under moto and validates whatever it writes. The
>   hand-built frames elsewhere encode what we *believe* Silver looks like; only this one uses
>   what it *is*, so it is what fails when the suites and the pipeline drift apart.
> - **`requirements/dq.txt` was verified, not just written**: a clean venv with the pinned set
>   (GX 1.20.0 / pandas 2.2.3 / pyarrow 20.0.0 — the pandas Glue actually runs) validates the
>   real prod data green. Worth doing because local dev is on pandas 3.0.5, where
>   `tipo_sorteo` infers as `str` while 2.2.3 gives `object` — the dtype-inference gap PR-030
>   flagged. Both pass, since the expectations used are dtype-agnostic.
> - Coverage ratchet 42 → **56** (`src/loteria/dq` at 100%).
> - **Follow-up, deliberately not done here:** referential integrity — every
>   `premios.numero_sorteo` existing in `sorteos` — is the one high-value check missing. It
>   needs a value set computed at run time, which cannot live in a committed static suite, so
>   it belongs with PR-033's runtime wiring or PR-035.

## PR-033 — DQ gate in Step Function
**Prompt:**
```
After the silver crawlers succeed and before the Gold CTAS map state, add:
  RunSilverDQ state that triggers an aws_glue_job (new) "loteria-silver-dq" — a Python Shell job that pip-installs great-expectations and runs the suites from PR-032.
If DQ fails, transition to a Fail state that publishes to the SNS alerts topic with the failure details. Gold is NOT built when DQ fails.
```

> **Notes from executing it (2026-09-14):** the gate is wired, 28 new tests, coverage
> ratchet 56 → **67**. Runbook: `docs/runbooks/PR-033-dq-gate.md`.
>
> - **🚨 The prompt's job type is wrong and PR-032 had already proved it.** "A Python Shell
>   job that pip-installs great-expectations" cannot work: GX 1.x needs Python >= 3.10 and
>   Python Shell offers only 3.6/3.9 (PR-020). The job is `glueetl` on **Glue 5.0**
>   (Python 3.11). It never creates a `SparkContext` — we are buying an interpreter version
>   and paying for a Spark cluster to get it, which at `2 × G.1X` once a week is a few cents
>   and still beats the alternatives (rewrite 20 expectations against GX 0.18, or run the
>   gate on Lambda/Fargate and maintain a second runtime).
> - **PR-032 left a half-finished entry point in `dist/`, and it would not have run.**
>   `dist/loteria_silver_dq.py` (2026-08-15, gitignored, referenced by nothing) imported
>   `format_report` and `summarize_failures` from `loteria.dq.runner`. `format_report` lives
>   in `scripts/run_dq.py`; `summarize_failures` did not exist at all. It would have raised
>   `ImportError` on the first job run. Recovered as `src/loteria/dq/glue_entrypoint.py`, and
>   both functions now live in the library — which is the right home anyway, because the CLI
>   and the job must render the same verdict or the SNS alert stops matching the log it tells
>   you to open. Side effect worth noting: moving them out of `scripts/` (not measured) into
>   `src/` (measured) is most of the coverage jump, taking `dq/runner.py` 58% → 100%.
> - **`awsglue.utils.getResolvedOptions` was dropped, not merely avoided.** It raises for any
>   name in its list that was not supplied, so the optional arguments needed hand-rolled
>   parsing regardless — and two parsers that disagree is worse than one. Parsing everything
>   ourselves also keeps the module importable without `awsglue`, which only exists inside
>   Glue, and is the only reason `tests/unit/test_glue_entrypoint.py` can exist at all.
> - **A separate READ-ONLY IAM role, not `glue_job_role`.** Reusing the transform role was one
>   line, but that role carries `s3:PutObject`/`s3:DeleteObject` on both data buckets. A
>   validator that can modify what it validates is not a gate: the whole value of this PR is
>   an independent assertion that Silver is fine, so the asserting thing must not be able to
>   change Silver.
> - **⚠️ MODULE CYCLE, and the workaround has a maintenance cost.** The Fail path publishes to
>   the SNS alerts topic, which `module.observability` owns — but observability already
>   consumes `module.orchestration` (the dashboard and alarms name the state machine, the
>   gold-purge Lambda and the weekly rule). Passing the output back is a cycle Terraform
>   rejects. The ARN is therefore **constructed from the name** in `terraform/main.tf`, which
>   is already this stack's pattern (`modules/iam` builds the state-machine, gold-purge and
>   log-group ARNs the same way). **A plan will NOT catch a rename**: both sides stay valid
>   strings and the failure is an `AccessDenied` at the first DQ failure — i.e. exactly when
>   nobody wants to debug it. Lifting the topic into its own module is the real fix and is a
>   state move for one string; deferred.
> - **No `Retry` on `RunSilverDQ`, and that is a decision.** Every other Task in the machine
>   retries, so the absence needs stating: a failed expectation is deterministic — the same
>   immutable Silver validated twice gives the same verdict — so a retry would burn a second
>   Glue run to reach the identical conclusion and delay the alert by a full job duration.
> - **The alert names the suite, the expectation and the column**, because PR-025's
>   `sfn_execution_failed` alarm already covers "an execution failed". This state exists to
>   make the failure *actionable*, not visible, and there is a test whose only job is to fail
>   if that message ever degrades to "DQ failed".
> - **Why the gate sits AFTER the crawlers** even though the DQ job reads Parquet directly
>   from S3 with boto3 and does not need the catalog: running it after means a green verdict
>   describes the exact state Gold is about to read, and it inherits PR-026.1's guarantee
>   that the crawl finished — so "DQ passed but Gold missed the newest sorteo" cannot happen.
> - **The gate protects the OLD data, not just the new.** `purge_and_load` drops each gold
>   table and empties its S3 prefix before the CTAS runs, so admitting bad Silver would not
>   merely write wrong Gold — it would destroy the last known-good Gold on the way. This is
>   audit fault B (PR-042) seen from the other side, and it is why the gate is worth more
>   here than the usual "don't publish bad numbers" argument.
> - **Not done, deliberately:** referential integrity (every `premios.numero_sorteo` exists in
>   `sorteos`), which PR-032 flagged for this PR. It needs a value set computed at run time
>   from a second dataset — a change to the runner's validation model, not to this PR's
>   plumbing. Carried to PR-035.
> - **A kill switch, `enable_silver_dq` (default true), ported from the abandoned first
>   attempt.** With it false, `module.etl_glue` creates neither the job nor its log group and
>   the state machine renders **byte-identically** to its pre-PR-033 form — so the stack is
>   applyable before the artifacts are built, and the rollback is a variable flip rather than
>   a revert. ⚠️ The three states are gated as a **JSON string** that is then `jsondecode`d,
>   not as `cond ? {...} : {}`: Terraform needs both branches of a conditional to unify to one
>   type, and an ASL state map is heterogeneous by construction (a `Task` has
>   `Resource`/`Parameters`/`Catch`, a `Fail` has `Error`/`Cause`, sharing no attributes), so
>   the direct form fails with *"the 'true' value includes object attribute
>   \"SilverDQFailed\", which is absent in the 'false' value"*. A real type mismatch, not a
>   Terraform quirk. One root variable feeds both modules on purpose — the gate and the job it
>   starts have to appear together.
> - **⚠️ HISTORY: this PR was attempted once before, and it was NOT rejected.** PR #38
>   (2026-08-15) implemented essentially this same design and was **closed unmerged** on
>   2026-08-19 with no comment, no review and no failing check. The forensics: #38's base was
>   still `feat/PR-032-gx-silver-suite`, and its state was `CONFLICTING`/`DIRTY`. The PR body
>   had assumed *"GitHub retargets to master automatically when #37 merges"* — **it did not**,
>   so when #37 merged and its branch was deleted, #38 was left pointing at a base that no
>   longer existed and became unmergeable. The 84-second sequence at 02:05–02:07 tells the
>   rest: #38 closed, #39 (PR-034) merged **into the PR-033 branch** to consolidate the work,
>   and #40 auto-closed one second later when its own base was deleted by that merge. The
>   scraper outage began the next day (2026-08-20) and buried it. **Lesson: do not stack PRs
>   in this repo.** Each roadmap PR branches from `master` and merges to `master`.
> - **Work still stranded on `origin/feat/PR-033-dq-gate`** (kept, not deleted): PR-034's
>   complete `.github/workflows/ci.yml` (241 lines) plus `terraform/.checkov.baseline`, and on
>   `origin/feat/PR-035-coverage-85` a coverage arc reaching **98.45%** (149 → 257 tests, the
>   four 0% modules brought to ~98%). Both to be rescued as independent PRs off `master`. Note
>   this PR's ratchet of 67 is superseded the moment PR-035 lands.
> - **Verified without running the pipeline** (no scrape.do credits spent): 178 tests green,
>   `terraform validate` clean, the state graph checked statically (every `Next` target names
>   a real state), and the built artifacts executed standalone with only
>   `loteria_dq_lib.zip` on `sys.path` — reaching the real S3 call before failing on
>   deliberately fake credentials, which proves the `--extra-py-files` layout resolves.
>   The ASL itself still needs `aws stepfunctions validate-state-machine-definition` against
>   a real plan (step 2 of the runbook) — that needs AWS and is the owner's step.

## PR-033.1 — What the first real runs exposed (unplanned)

**Filed 2026-09-20, after PR-033 was applied and verified in prod.** Same class as PR-026.1
and PR-031.1: defects found by running the thing, not deferred scope. Neither was visible
from the code, a plan, or a green test suite — both needed a real Glue run to surface.

> **First, the good news, because it is what makes the rest worth fixing.** The gate was
> exercised in **both** directions. `jr_6873896084f7a785…` validated the real Silver layer —
> 20 expectations over 115 sorteos and 121,050 premios — and returned `DQ RESULT: PASS`.
> `jr_910c242d010ea13c…`, pointed at a prefix that does not exist, returned `FAILED` with
> *"No Silver data to validate … this is a wiring problem, not a data-quality one"*. A gate
> that has only ever passed is indistinguishable from no gate; this one has been seen to
> close, and to say why in the string the SNS alert carries.

### Defect A — a 22-minute startup against a 30-minute timeout

**Measured.** `StartedOn` 01:41:10 UTC, the script's first log line at 02:02:30,
both suites validated by 02:02:45, `CompletedOn` 02:02:57. So **21m20s of provisioning plus
`pip install great-expectations==1.20.0`, then 15 seconds of actual work.** `ExecutionTime`
reports 86s, because it is billed time and excludes the startup — which is also why the
console shows `Duration 0s` for most of the wait, and why that is not a hang.

> **Corrected 2026-09-20 (PR-033.2).** This section first said the 22 minutes happen on
> *every* run. Four runs say otherwise, and only the first two were slow:
>
> | Run | Wall clock | `ExecutionTime` |
> |---|---|---|
> | `jr_6873…` 09-16 01:41 UTC | **21m47s** | 86s |
> | `jr_910c…` 09-16 02:12 UTC | **20m08s** | 82s |
> | `jr_3c3d…` 09-17 18:04 UTC | 1m56s | 95s |
> | `jr_68c2…` 09-20 20:10 UTC | 1m44s | 96s (console: start-up **8 seconds**) |
> | `jr_2101…` 09-20 20:55 UTC | 2m09s | 115s |
>
> The billed work is constant at ~90s; only the startup collapsed. The obvious explanation
> is that Glue caches the resolved `--additional-python-modules` environment per job after
> the first run, but **that is a hypothesis, not a measurement** — AWS does not document it
> here, and four runs on three days cannot separate it from a slow PyPI afternoon on the
> 16th. Treat the 22 minutes as the **worst case this job has actually shown**, which is
> what a runaway guard must be sized against, and not as the expected duration.

**Why it is a defect and not just slow.** At `timeout = 30` a 22-minute startup left ~8
minutes of margin. A slow PyPI day trips the timeout, the state machine's `Catch` turns that
into `NotifyDQFailure`, and the result is a **false** "Silver failed quality" email *and*
Gold not built. An infrastructure hiccup wearing a data-quality alert's clothes is how a
gate loses its credibility — the PR-031 canary lesson, third appearance. That the fast path
is now the common one narrows the window; it does not close it, and a cache that AWS never
promised is not something to size a timeout against.

It is also a weekly runtime dependency on PyPI resolving the same way it did last week,
which is the failure #45 already had to fix once as version drift.

**Done in this PR:** `dq_timeout_minutes` 30 → 60, with a validation rejecting anything
below 30. Costs nothing — billed time excludes startup — and it is a stopgap, not a fix.

**The fix, deliberately not done here:**
```
Stop installing at runtime. Two options, in order:

1. Vendor GX into the --extra-py-files zip that scripts/build_dq_package.sh already builds.
   Glue 5.0 already ships pandas and pyarrow (the heavy, compiled ones), and requirements/dq.txt
   already pins the exact set that was verified against prod. This is incremental: it extends
   a script that exists, and it removes the PyPI dependency from the weekly path entirely.
   Watch for: GX's own transitive deps that are NOT pure Python, and the zip size limit.

2. Move the gate off Glue onto a Lambda container image. PR-033's own note says it plainly —
   "we are paying for a Spark cluster to get an interpreter version". That reasoning counted
   dollars (2 cents a run) and was right; it never counted WALL CLOCK against the timeout,
   which is the cost that actually showed up. A container image with GX baked in starts in
   seconds, runs Python 3.12, and this workload is 121k rows of pandas that never touches
   Spark. Bigger change: new runtime, new IAM, new build path.
```

### Defect B — the per-job log group was empty

**Measured.** Zero streams in `/aws-glue/jobs/loteria-silver-dq-prod` after a successful
run. Every line — the JSON logs and the `DQ RESULT` verdict — landed in the account-wide
`/aws-glue/jobs/output`, with `/aws-glue/jobs/error` alongside.

**Why.** `--continuous-log-logGroup` ships **Spark's log4j output**, and
`loteria.dq.glue_entrypoint` deliberately never creates a `SparkContext`. No Spark, no
log4j, nothing to carry. `JobRun.LogGroupName` reporting the base `/aws-glue/jobs` rather
than the configured group is the tell. PR-033's comment asserting that continuous logging
"carries the application logs, which is where `format_report`'s verdict lands" was simply
wrong, and nothing could have caught it short of a real run.

**What it cost.** The runbook sent a woken-up reader to an empty group. And the log group
resource, its 30-day retention, and the `CKV_AWS_158` checkov exception **accepted
deliberately for it** were all paying for something that received nothing.

**Done in this PR:** the job writes to the group itself —
`loteria.common.cloudwatch_logging`, wired through a new `--DQ_LOG_GROUP` job argument so
Terraform stays the single source of the group's name. Two properties are held by tests
rather than by good intentions:

- **It never raises.** A CloudWatch throttle or outage must not fail a data-quality run; the
  handler disables itself, says so once on stderr, and stdout logging continues.
- **It never creates the log group.** Terraform owns the group *and its retention*; a group
  created by application code defaults to "never expire" and becomes a silent permanent
  bill — precisely the drift PR-023 exists to prevent.

The continuous-logging arguments are kept: they cost nothing and would start working the day
this job ever touches Spark. They are just not what makes the group non-empty.

The verdict goes to the group through a non-propagating logger carrying only the CloudWatch
handler, so it is not also emitted on stdout a second time, JSON-escaped. stdout keeps the
JSON envelope for machines; the group gets plain readable text for humans, because "the
whole output of this job is a verdict someone reads after an alert" is what the group is for.

---

## PR-033.2 — The fix for defect B did not work in prod (unplanned)

**Filed 2026-09-20, from the first run of PR-033.1's own fix.** `jr_68c2…` succeeded, the
gate passed, and the per-job log group came up with **one stream and zero events** — the
same symptom PR-033.1 existed to fix, arrived at by a different route. `storedBytes: 0` was
not reporting lag; `get-log-events` returned nothing.

**The job said why, eight times, in `/aws-glue/jobs/output`:**

```
[cloudwatch-logging] disabled for /aws-glue/jobs/loteria-silver-dq-prod/38025ca0-…:
Parameter validation failed: Invalid length for parameter logEvents, value: 0,
valid min length: 1. Logs continue on stdout.
```

**Cause — a logging handler that calls AWS feeds itself.** The handler sits on the **root**
logger, and the boto3 calls it makes to ship a record emit records of their own:
`botocore.credentials` alone produced ~180 of them in a 96-second run. Each came back into
`emit()` *while a send was in flight*, and `flush()` checked for an empty buffer **before**
calling `_ensure_stream()` rather than after:

```python
if self._disabled or not self._buffer:   # one event buffered → carry on
    return
self._ensure_stream()                    # create_log_stream → botocore logs → emit() →
                                         # nested flush() drains the buffer
batch = self._buffer[:MAX_BATCH_EVENTS]  # → []
client.put_log_events(logEvents=batch)   # ParamValidationError → the handler disables itself
```

The handler kept every promise it made — it did not raise, it did not create the group, the
job stayed green and `DQ RESULT: PASS` reached stdout intact. It just never wrote to the
group it exists for. **A fallback that works is indistinguishable from a fix that doesn't**,
which is the whole reason this had to be checked by reading the group rather than by reading
the plan.

**Why the PR-033.1 suite was green against it.** Every test injected a fake client, and a
fake client does not log. The recursion needs a client that talks while it works, which is
the one thing a stub never does. The new tests use one; all four fail against the PR-033.1
handler.

**Done in this PR:**

- A re-entrancy guard (`_sending`): a nested flush is a no-op, so a send always owns the
  batch it sliced. Records arriving mid-send stay at the back of the buffer and ride out
  with the next one, rather than being dropped.
- The empty-batch check moved to immediately before `put_log_events`, kept as belt and
  braces for a future caller that flushes by hand.
- `_disable()` made idempotent — it promised "once" in its own docstring and printed eight
  times.
- `quiet_sdk_loggers()`: the AWS SDK loggers are raised to `WARNING` when the handler is
  attached. The guard alone leaves the feedback loop *bounded* rather than broken, and a
  group whose job is to hold one readable verdict must not be 88% credential chatter.

**Deploy note:** code-only. No Terraform change, so no `apply` — rebuild
`scripts/build_dq_package.sh` and re-upload both artifacts.

### Verified in prod (2026-09-20)

`jr_21010e715de41c13…`, the first run after the re-upload. The per-job log group finally
holds what it was created for:

```
20:57:21 INFO silver-dq         Silver DQ starting
20:57:28 INFO loteria.dq.runner Loaded Silver dataset      (sorteos)
20:57:28 INFO loteria.dq.runner Suite validated            (silver_sorteos)
20:57:34 INFO loteria.dq.runner Loaded Silver dataset      (premios)
20:57:34 INFO loteria.dq.runner Suite validated            (silver_premios)
20:57:34 INFO silver-dq.verdict [PASS] silver_sorteos: 11 expectations, 116 rows from 116 files
                                [PASS] silver_premios: 9 expectations, 121945 rows from 116 files
                                DQ RESULT: PASS
```

Six events, and **exactly** the six the job means to emit. The run before this one put 204
lines on stdout, ~180 of them `botocore.credentials` — so `quiet_sdk_loggers` is doing the
other half of the work, and the verdict is not buried in chatter. It arrives as ONE
multi-line event, which is the whole reason the group gets a plain formatter rather than the
JSON one. No `[cloudwatch-logging] disabled` anywhere.

**A trap for whoever checks this next:** `describe-log-streams` reported `storedBytes: 0`
*and* `firstEventTimestamp == lastEventTimestamp` while `get-log-events` returned all six
events. Those fields lag by minutes. **Read the events, not the metadata** — reading the
metadata is how a working group looks broken, and it is the same field that made the broken
group look merely slow on 2026-09-16.

---

## PR-034 — GitHub Actions CI
**Prompt:**
```
Create .github/workflows/ci.yml on push + PR:
- jobs.lint: ruff check, ruff format --check, terraform fmt -check
- jobs.test: pytest -v --cov, fail under 70% (matches pyproject)
- jobs.tf-validate: terraform init -backend=false, terraform validate
- jobs.tf-security: tfsec, checkov against terraform/
- jobs.python-security: bandit -r src/
- jobs.build-artifacts (on push to master only): builds layer.zip + code.zip + glue_transformer.zip and uploads as workflow artifacts.

Also create .github/workflows/scraper-canary.yml: weekly cron Sundays 18:00 UTC running tests/integration/test_scraper_contract.py with RUN_LIVE_SCRAPER=1 and SCRAPE_DO_TOKEN from secrets. On failure, opens a GitHub issue with the failure log.
```

> **Notes from executing it (originally 2026-08-15; rescued onto `master` 2026-09-14).**
>
> - **⚠️ This work existed for a month without being on `master`.** It was written as GH #39,
>   stacked on PR-033's #38, and #39 was **merged into the PR-033 branch rather than into
>   `master`** — so it shows as "merged" on GitHub while `master` never received a single
>   line of it. When #38 was closed (see PR-033's notes: a broken base, not a rejection), the
>   whole CI went with it. Recovered by cherry-picking `89b4d3e` onto a branch off `master`.
>   **This is the strongest argument in the repo against stacking PRs**: a "merged" badge on
>   #39 is what made it invisible for a month.
> - **`scraper-canary.yml` is deliberately NOT created here**, despite the prompt listing it.
>   PR-031 already shipped it, on a **Wednesday** cron rather than the prompt's Sunday (Sunday
>   lands inside the post-draw Cloudflare waiting-room window that the Thursday pipeline move
>   exists to dodge). Recreating it would clobber that decision.
> - **Every gate was RUN before being wired in; three of six would have been red on arrival**,
>   and each got a different answer rather than `continue-on-error`:
>   - **ruff**: 39 errors + 8 files to reformat, **all** in `notebooks/` and `miscellaneous/`,
>     none in `src/`, `tests/` or `scripts/`. Not a regression — pre-commit only ever passes
>     ruff the *changed* files, so the repo had never been linted in full. Both directories
>     are `extend-exclude`d rather than reformatted: neither ships, and nbstripout already
>     owns notebook hygiene. `ruff check .` now means "the code that runs in AWS".
>   - **checkov**: 71 failures against existing infrastructure, mostly deliberate (SSE-S3 over
>     a KMS CMK, no access logging on a personal project). Baselined in
>     `terraform/.checkov.baseline`, so CI fails only on **new** findings — a ratchet, exactly
>     like `--cov-fail-under`.
>   - **bandit**: 5 findings, all false positives for these runtimes, all resolved **inline**
>     rather than baselined, so the job blocks with no exemption file.
> - **Trivy, not tfsec**, which the prompt names: Aqua has folded tfsec into Trivy (same
>   engine, still maintained). Wiring a new CI to a tool its authors stopped developing is not
>   a defensible starting point. Non-blocking with a SARIF upload, because its finding volume
>   here has never been measured — shipping a blocking gate whose output nobody has read is
>   the mistake the checkov baseline exists to avoid.
> - **The coverage threshold is NOT restated in CI.** `pyproject` carries a ratchet, not the
>   prompt's 70; `pytest` reads `--cov-fail-under` from `addopts`. Duplicating it would
>   guarantee the two drift.
> - **No AWS credentials anywhere in the workflow.** `terraform init -backend=false` means
>   nothing in CI can reach the account. `terraform/bootstrap` is a separate root module and
>   gets its own validate.
> - **Changes made during the rescue** (the branch was written against a repo state that no
>   longer exists):
>   - `build-artifacts` no longer uploads `dist/loteria_silver_dq.py` / `loteria_dq_lib.zip`.
>     Those come from PR-033, which is not on `master` yet, and `if-no-files-found: error`
>     would have failed the job. A comment says to add them back when PR-033 lands.
>   - The `# nosec B108` on `extract_lottery_data` was reapplied by hand: PR-031.1 rewrote
>     that module in August, so the original hunk no longer applied.
>   - **Two entries were stripped from the checkov baseline** — `aws_glue_job.silver_dq` and
>     its log group. The baseline was generated on a branch that already contained PR-033, so
>     it was pre-accepting findings for resources that do not exist yet. A baseline's whole
>     contract is "the findings accepted **today**"; pre-suppressing tomorrow's is how a
>     ratchet quietly stops ratcheting.
> - **Gotcha worth remembering: bandit scans comment TEXT for its suppression token**, so an
>   explanatory comment that quotes `nosec` becomes a suppression and silently disables the
>   check. The comments in `transformer.py` name the check id instead.
> - **A second bandit gotcha, found during the rescue.** The job logs two
>   `WARNING nosec encountered (B108), but no failed test` lines for `transformer.py:245-246`.
>   They are **not** dead suppressions: bandit 1.9.4 attributes an f-string's B108 to a
>   different column than the one it reconciles `nosec` against, so it both skips the finding
>   and warns that it found nothing to skip. Verified by deleting the two markers — B108 fires
>   at `245:31` and `246:31` and the job goes red. Documented in `ci.yml` so nobody "cleans up"
>   the warning into a broken build.
> - **⚠️ The first real CI run (#45) went red, and BOTH failures were genuine** — which is
>   the best possible argument for this PR. Neither was reproducible locally.
>   - **`test`: great-expectations version drift.** `pyproject`'s `dq` and `dev` extras
>     floated at `>=1.0,<2.0` while `requirements/dq.txt` — what the Glue job installs — was
>     pinned to `1.20.0`. A clean runner resolved **1.23.0**, and since the committed suite
>     JSON records the GX version that produced it, `test_dq_suites` failed with no code
>     change. It would have kept failing at random on every future GX release, and worse,
>     CI was validating a different GX than production runs. Both extras are now pinned to
>     `1.20.0`. Bumping GX becomes a deliberate act: change all three pins and run
>     `make dq-sync`. **A repo about data-quality reproducibility was testing against
>     "whatever PyPI shipped this morning".**
>   - **`tf-security`: the Trivy action tag does not exist.** Pinned to `0.28.0`; the action
>     publishes **`v`-prefixed** tags and is now on `v0.36.0`. The original author recorded
>     that Trivy "could not be installed in the environment where this PR was written" — so
>     the version was never verified, and this is exactly the failure that implies.
>     **The real damage was structural**, though: GitHub resolves every action in a job
>     *before* running any step, so the bad reference killed the job in 2 seconds and
>     **checkov never ran at all**. A deliberately non-blocking scanner silently disabled a
>     blocking one. Trivy now lives in its own job, so it can only ever fail itself — which
>     is what this file's own header already claimed about job independence, just never
>     applied here.
> - **Verified locally before pushing, all six jobs**: `ruff check .` + `ruff format --check .`
>   on the pinned 0.6.9 (clean, 32 files), `terraform fmt -check -recursive` (clean),
>   `pytest` (150 passed / 6 skipped), `terraform validate` on both root modules, `checkov`
>   against the baseline (exit 0), `bandit -r src/ -q` (exit 0), and `make build` (exit 0,
>   producing exactly the three uploaded paths).

## PR-035 — Bump coverage gate
**Prompt:**
```
Ratchet pyproject.toml's --cov-fail-under from 70 to 85. Add tests as needed to clear the bar (focus on parser + transformer edge cases).
```

### Outcome — 70 → 98, and most of the work was already written

**The prompt's focus was stale.** `parser.py` has been at 100% since PR-029 and
`transformer.py` at 86% since PR-030. The missing points were four modules that had never
been executed by a test at all: `extractor/scraping.py`'s orchestration, `lambda_handler.py`,
`gold/purge_and_load.py` and `observability/object_count.py`.

**Most of it was rescued, not written.** `origin/feat/PR-035-coverage-85` had taken coverage
to 98.45% in August 2026 and was lost when the stacked-PR chain collapsed — the work was
never reviewed and never judged, only stranded (see the note at the top of this file). Three
of the modules it covered have not changed since, so `test_gold_purge.py`,
`test_object_count.py`, `test_common.py` and the transformer additions applied verbatim and
passed on the first run.

What did **not** apply was the extractor: PR-031.1 rewrote `scraping.py` between then and
now. The stranded page fixture used `div.card-body div.row[2]` — the exact container the
August redesign filled with legal boilerplate, and the reason PR-031.1 exists. So
`extract_lottery_data`'s tests were rebuilt against `div.lista-premios-columnas`, and split
into their own file: `scraping.py` reads secrets at *import* time, so two fixtures importing
it with different fakes in one file is a trap for whoever adds the next test.

**The gate is 98, not 85.** `pyproject.toml`'s convention since PR-029 is that the number
sits at what the suite achieves; an 85 gate on a 98.52 suite leaves 13 points of silent
regression room, which is the opposite of a ratchet. 85 was a floor and it is met. The 12
statements still uncovered are dead ends, each one listed and justified in `pyproject.toml`.

**Three findings, none of them fixed here** — a coverage PR must not change what the weekly
production run does. All three are filed as PR-035.1 below.

---

## PR-035.1 — Three things writing the tests found (unplanned)

**Filed 2026-09-20.** None of these is a coverage problem; they are what coverage *reveals*.
Same class as PR-026.1, PR-031.1 and PR-033.1: defects found by exercising code, not
deferred scope.

### A — the extractor's idempotency guard is dead

`check_if_sorteo_exists` asks for `processed/year=<Y>/sorteo=<N>/sorteos.parquet`, with the
prefix **hardcoded** and no override (`s3_utils.py:18`). Nothing has written `processed/`
since **2025-11-24**: Silver moved to `silver/`, and the transformer passes its own prefix
explicitly (`transformer.py:92`) — which is why *its* idempotency still works and the
extractor's does not.

The branch cannot fire in production. A retry or a manual re-run re-scrapes a draw already
captured: two scrape.do requests at 25 credits each, and a rewrite of `raw/` that adds a new
version on a versioned bucket. Not corruption — a guard the code claims to have and does not.

**Fix:** give `check_if_sorteo_exists` the same explicit-prefix treatment the transformer
already has, defaulting to `silver/sorteos/`. Small, but it changes what a production run
does, which is why it is not in PR-035. `test_extract_lottery_data.py::TestTheIdempotencyGuardIsDead`
pins today's behaviour and fails the day it is fixed — deliberately.

### B — the draw-date regex truncates instead of failing

`FECHA DEL SORTEO:\s*([\d/]+)` is an unanchored character class, so `01/06/20XX` matches the
prefix `01/06/20` and the draw is filed under `raw/year=20/`. The
`except (ValueError, IndexError)` fallback to `"unknown"` never fires, because nothing
raised — those two statements are unreachable today.

`year=unknown` is greppable; `year=20` looks like real data and the crawler registers it
without complaint. **Fix:** anchor to `\d{2}/\d{2}/\d{4}`. Every real capture so far is
well-formed, which is why this is a latent defect rather than an outage.

### C — one malformed header kills the whole transform

`process_header` raises `ValueError("The HEADER does not contain the expected format.")` on a
header missing `REINTEGROS`, and nothing catches it: the exception aborts the run for every
*other* raw file in the batch, before anything is written. A draw type that omits the line —
or a redesign that renames the label — is a full weekly outage rather than one skipped
record.

This is **fault E's territory (PR-044, `quarantine/`)** and should be fixed there rather than
twice. Noted here because the test that pins it
(`test_transformer.py::test_a_header_with_no_reintegros_line_at_all_is_rejected_by_the_parser`)
is the one that has to change when the quarantine lands, and because it is the reason
`transformer.py:204-206` is unreachable dead code.

---

# Phase 6 — Documentation & diagrams

## PR-036 — README rewrite
**Prompt:**
```
Rewrite README.md so it answers, in this order:
1. What this project is (1 paragraph + the architecture diagram)
2. Why it exists (the historical-data gap)
3. Quick start — clone, prereqs, 5 commands max to deploy
4. Architecture overview (medallion + diagram link)
5. Data quality story (how GE + the scraper canary work together)
6. Observability story (dashboard + alarms screenshot)
7. How to run tests
8. Cost (approximate monthly with one weekly run)
9. Roadmap / future work
10. ADRs (link to docs/adr/)

Move the existing "Challenges Faced" content into docs/challenges.md (renamed from challanges_faced.md, fixing the typo).
DELETE aws_etl_setup.md (it describes a defunct design).
```

## PR-037 — Diagrams in draw.io (XML committed)
**Prompt:**
```
Create docs/diagrams/ with .drawio source files (also export to PNG into docs/diagrams/png/):
1. 01_network.drawio (NAT ON/OFF) — refresh from existing
2. 02_end_to_end.drawio — Step Functions, EventBridge, Lambda, Glue, Crawlers, Athena, SNS, QuickSight
3. 03_medallion.drawio — Bronze (raw/) → Silver (silver/) → Gold (gold/) with the 7 gold tables
4. 04_observability.drawio — CloudWatch dashboards, alarms, SNS → email
5. 05_cicd.drawio — GitHub Actions → tfsec/bandit/pytest → master → manual deploy

Replace images in README with references to docs/diagrams/png/*.
```

## PR-038 — ADRs
**Prompt:**
```
Create docs/adr/ with one file per ADR (use the MADR-lite format):
- ADR-001-vpc-separation.md (move existing vpc-separation.md here, rewrite into ADR shape)
- ADR-002-glue-vs-lambda-for-transform.md (lift from challanges_faced.md §7)
- ADR-003-scrape-do-mx-proxy.md (lift from §6)
- ADR-004-athena-ctas-for-gold.md (new — explain the decision from DoD §4 D1)
- ADR-005-dq-gate-in-step-function.md (new — explain DQ-as-blocker design from PR-033)
- ADR-006-single-env-single-account.md (new — explain why no dev/prod folders)

Each ADR has: Status, Context, Decision, Consequences.
```

---

# Phase 7 — Developer experience

## PR-039 — Fill in the Makefile
**Prompt:**
```
Fill in the Makefile targets stubbed in PR-001:
- bootstrap: cd terraform/bootstrap && terraform init && terraform apply
- secrets: bash scripts/seed_secrets.sh (creates the secret in Secrets Manager from prompts)
- build: build layer.zip, code.zip, glue_transformer.zip
- deploy: cd terraform && terraform init && terraform apply
- test: pytest -v --cov
- dq: python scripts/run_dq.py
- destroy: refuse unless `CONFIRM=YES` env var is set (the prod buckets have prevent_destroy anyway, but be paranoid)
- lint: ruff check && terraform fmt -check
- fmt: ruff format && terraform fmt -recursive
- tf-plan: cd terraform && terraform plan -out=tfplan
- sagemaker: cd terraform && terraform apply -var=enable_sagemaker=true
```

## PR-040 — `.envrc.example` + final README polish
**Prompt:**
```
Create .envrc.example documenting required env vars: AWS_PROFILE, AWS_REGION, SCRAPE_DO_TOKEN, LOTERIA_SECRET_NAME, ALERT_EMAIL.
Update README "Quick Start" to reference `cp .envrc.example .envrc && direnv allow`.
Add a "Tested deploy" badge / note: "Fresh-account deploy verified on YYYY-MM-DD" — once the owner does a clean test deploy.
```

---

# Phase 8 — Structural repairs (from the 2026-09-14 pipeline audit)

A read-only audit of the whole pipeline on 2026-09-14 (no pipeline run, no scraper credits
spent) found five design defects that are **not** blocking anything today and will each get
harder to fix the longer the lake grows. They are written down here so they stop being
folklore. None of them is urgent; all of them are cheaper now than later.

The audit's headline finding — the Great Expectations suites from PR-032 exist, are tested,
and are **called by nothing in the pipeline** — is PR-033 and is not repeated here.

## How to work this phase — 8A → 8E, not 041 → 045

> ⚠️ **Numeric order is not execution order.** The numbers come from the audit's fault
> letters and from `layouts/diagram.html`, which is published and already links to them.
> The dependency order is different, and it is the sub-phase letters that say what to work
> next. Do **not** read this phase top-to-bottom the way the rest of this file is read.

Each defect is split into sub-PRs. The splits are not ceremony: in 8A the split is what
separates a reversible change from an irreversible one, and in 8B and 8E it is what keeps a
mechanism change reviewable apart from the data change it enables.

| Order | PR | Sub-PRs | Why it sits here |
|---|---|---|---|
| **8A** | 041 | `.1` stop the writes · `.2` strip the config · `.3` tear the bucket down | **First — it deletes a write path, so every PR after it touches one less place.** Do it before 045 adds columns, or 045 has to decide whether the flat copies carry lineage too. |
| **8B** | 042 | `.1` build beside and swap · `.2` retire old generations | **Before anything changes how Gold is built.** 8E makes the build cleverer; doing that while a failed build still destroys the last good copy multiplies the blast radius. The section below already says C is easier after B — this is that, made binding. |
| **8C** | 045 | `.1` write the columns · `.2` make lineage queryable | `run_id` is the join key both 8D and 8E want. Additive, cheap, and it is the only sub-phase that gets *more* expensive every week (222 files today, and each Thursday adds two). |
| **8D** | 044 | `.1` make the loss visible · `.2` persist the rejects | Quarantine records reference 8C's `run_id`; without it a quarantined row cannot be tied to the run that rejected it. |
| **8E** | 043 | `.1` measure · `.2` the four incremental tables · `.3` decide the three aggregates | **Last.** The largest change in the phase, and it is only safe once publication is atomic (8B) and rows are traceable (8C). |

**Phase 8 is done when** `layouts/diagram.html` has no red boxes left and its five-defect
`<details>` table is rewritten as history, each row naming the PR that closed it.

---

## PR-041 — Retire the `simple` bucket and the legacy `processed/` prefix
**Fault A · owner decision on 2026-09-14: delete it.**

**The defect.** `transform_lottery_data()` writes every draw's Parquet **twice**: once to
`silver/{dataset}/year=/sorteo=/` in the partitioned bucket, and once to a flat
`{simple_prefix}{dataset}_{N}.parquet` key in `lottery-data-simple-prod`
(`src/loteria/transformer/transformer.py:244-258`). On top of that, the Glue job still
receives `--PROCESSED_PREFIX = "processed/"` (`terraform/modules/etl-glue/main.tf:82`),
a prefix the transformer's own comments already call legacy — the idempotency check was
moved off it in PR-016 ("✅ Idempotency check must be against SILVER (not legacy/processed)").

**Why it existed.** The flat bucket was the only way to eyeball the data before Hive-style
partitioning was in place — download one file, open it, done. That need is gone: Athena now
reads all three layers, and the Glue catalog registers Silver and Gold.

**Why it is a defect now.** Two copies of the same data with only one declared owner. It
costs storage forever, it invites drift (nothing verifies the two copies agree), and it
leaves a newcomer asking which one is the source of truth. Every write also pays a second
`put_object` for a file no reader consumes.

**Prompt:**
```
Fault A from the 2026-09-14 audit. Retire the duplicate write path.

1. src/loteria/transformer/transformer.py:
   - Drop the `simple_prefix` parameter and both simple-bucket uploads (sorteos + premios).
   - Silver becomes the only write target.
2. terraform/modules/etl-glue/main.tf: remove the `--PROCESSED_PREFIX` job argument and the
   SIMPLE_BUCKET wiring that only fed it. Check the IAM policy in modules/iam for a write
   grant on lottery-data-simple-prod and remove that too.
3. tests/unit/test_transformer.py: drop the simple-bucket assertions; add one asserting the
   transformer writes to exactly one bucket.
4. Do NOT delete any S3 data in this PR. Code and Terraform only.

Out of scope: emptying or deleting the bucket (see the runbook below — it is a separate,
deliberate, owner-run step).
```

**⚠️ Deleting the bucket is NOT a one-liner, and this is exactly where PR-002's safety net
bites us on purpose.** Write `docs/runbooks/PR-041-retire-simple-bucket.md` covering, in
order:
1. Inventory it one last time (`scripts/00_inventory_and_protect.sh` already produces the
   snapshot format) and commit the snapshot, so "what was in there" is answerable forever.
2. **The Deny policy from PR-002 blocks `s3:DeleteObject*` for every principal except the
   account root** — see the gold-purge experience. The policy has to come off (or be
   narrowed) before anything can be removed, and it should go back on if the bucket is kept.
3. **Versioning is on, so deleting objects only writes delete markers.** A real purge needs
   `list-object-versions` + `delete-objects` over *versions and* delete markers, or a
   lifecycle rule that expires noncurrent versions. `aws s3 rm --recursive` alone leaves the
   bytes (and the bill).
4. `prevent_destroy = true` is set on the bucket in `modules/storage` — Terraform will
   refuse to destroy it until that lifecycle block is deliberately removed.
5. Cheapest safe option to consider first: keep the empty bucket, drop the lifecycle to
   expire everything, and leave a `README` object explaining why it is empty. Storage cost
   goes to ~zero without ever running a destructive command against prod.

**Acceptance:** transformer writes once; `terraform plan` is clean; no `PROCESSED_PREFIX`
anywhere; the runbook exists and the owner has run (or deliberately deferred) the purge.

---

### Sub-PRs

**PR-041.1 — Stop the writes, keep every byte.** Gate both uploads behind a root variable
`enable_simple_bucket_writes`, threaded to the transformer *and* to `scraping.py:258-259`
— the extractor writes the raw `.txt` to the simple bucket too, which the prompt above does
not cover. Ship the flag defaulting to `true`, flip it to `false` in a second commit in the
same PR, so the rollback is one revert of one line.
*Before the flag, commit the no-reader evidence* under `docs/inventory/`: CloudTrail data
events for `GetObject` if they are enabled (if they are **not**, say so — absent logging is
not evidence of absent readers), `BytesDownloaded` over the longest window available, and a
repo-wide grep outside `scripts/policies/` and `docs/`.
**Acceptance:** a full run completes and the simple bucket's object count is *unchanged*
from the snapshot. **Out of scope:** any deletion.

> ⚠️ **Found at 041.1's apply, and not in the prompt below: the bucket has a granted
> READER.** `lottery-sagemaker-execution-role-prod` carries
> `lottery-sagemaker-s3-read-policy-prod`, whose entire content is `s3:GetObject` +
> `s3:ListBucket` on `lottery-data-simple-prod` and **nothing else**. So the one consumer this
> architecture ever contemplated was SageMaker, pointed at exactly the bucket being retired —
> which is also the honest answer to "why did the flat copies exist": they were the notebook
> layer. Nothing is running (two domains `InService`, zero apps, zero notebook instances) and
> the owner confirms they do not use it, but the *grant* is real and 041.2 must deal with it:
> stripping only the write grants would leave a SageMaker role whose sole data permission
> points at a bucket that is about to stop existing. Repoint it at `silver/` and `gold/` in
> the partitioned bucket, which is where the data a notebook would want actually lives.
>
> ✅ **Also verified at 041.1: nothing in the bucket is unique.** All 115 raw `.txt` and 116
> Parquet draws have a counterpart under the partitioned bucket's `raw/` and `silver/`
> (`set(simple) - set(partitioned)` is empty for both). Deleting it therefore cannot lose
> data — only a convenience copy. That is the fact 041.3's grace period was sized without,
> and it is why shortening the window is defensible.

**PR-041.2 — Strip the configuration surface.** Everything from the prompt above that is
now dead: `--PROCESSED_PREFIX`, the `SIMPLE_BUCKET` wiring, the write grants in
`modules/iam`, **the SageMaker read grant above**, and the `"simple"` key in `get_secrets()`
(`src/loteria/common/aws_secrets.py:46`). Leave the key in the Secrets Manager payload —
that is an owner edit, not Terraform's; record it in the runbook as a manual follow-up.
`README.md:111-112,141` still sells the dual-bucket strategy as a feature; that is the
README-vs-code contradiction the audit flagged, and it becomes true again here.
**Acceptance:** the plan shows IAM/Glue-job updates only. **If it shows a destroy on any
`aws_s3_bucket`, stop.**

> **PR-041.1 outcome (2026-09-20).** Evidence in
> `docs/inventory/2026-09-20-simple-bucket-readers.md`: 347 current objects (232
> `processed/` + 115 `raw/`), 540 versions + 2 delete markers, newest written 2026-09-17 by
> the weekly run. Nothing reads it — 23 code references, all writers or plumbing; every Glue
> catalog table resolves to the partitioned bucket; 44 Athena queries over 45 days mention it
> zero times. Two signals are blind and are recorded as such: **CloudTrail data events are
> not enabled for this bucket** and S3 request metrics are not configured.
>
> The flag turned out to cover **three** writes, not the two the prompt above lists — the
> extractor's raw `.txt` is the third, exactly as the sub-PR note warned. Both delivery
> routes (a Glue job argument, a Lambda environment variable) go through
> `loteria.common.config`, which keeps `"false"` meaning the same thing on both sides and
> keeps an unrecognised value ON, because a count that fails to stop moving is visible and a
> silent stop is not.
>
> **Applied 2026-09-20 22:31 UTC** (PR #53). Plan was `0 to add, 4 to change, 0 to destroy`:
> the job argument, the Lambda's environment variable *and* its code (`scraping.py` changed,
> and Terraform manages that zip), plus the known `gold_purge` phantom. The transformer's zip
> is NOT Terraform-managed and was uploaded by hand the same minute —
> `c20025f978cb2524736df6900dc84ea6`, verified byte-identical to `dist/`. Without that upload
> the flip would have been half-applied: the extractor stops, the transformer keeps writing,
> because code that has never heard of the argument ignores it.
>
> Verified live after the apply: job argument `false`, Lambda env var `false`, bucket at
> **347 objects**.
>
> ### The clock for PR-041.3
>
> **Starts 2026-09-20. Earliest teardown: 2026-10-20.** Four weekly runs fall inside it —
> 09-24, 10-01, 10-08, 10-15 — which is the point: the window is not a formality, it is four
> chances for a reader nobody knew about to notice its data has gone stale and say so. The
> evidence in `docs/inventory/` is blind to exactly that reader (CloudTrail data events are
> off for this bucket, request metrics are not configured), so the grace period buys with
> time what the evidence cannot prove. The cost is one bucket holding 9 MB it already held.
>
> **Abort condition, checked on 2026-10-20 before anything is deleted:**
> `aws s3 ls s3://lottery-data-simple-prod/ --recursive | wc -l` must still be **347**. If it
> moved, a writer nobody knew about is still running — find it before deleting a byte.

**PR-041.3 — Tear it down (irreversible, owner-run).** Execute the runbook above, after a
stated grace period of **at least 30 days** from 041.1's apply, with the date written down.
Abort condition: if the final object count differs from 041.1's snapshot, something still
writes to it — find it before deleting anything. The version purge should lift
`purge_and_load._empty_prefix`'s pattern rather than reinvent it; it already handles
versions *and* delete markers correctly.


## PR-042 — Make the Gold publication atomic
**Fault B.**

**The defect.** `src/loteria/gold/purge_and_load.py` runs `DROP TABLE IF EXISTS` **and**
empties the table's S3 prefix, then returns the `CREATE TABLE ... AS SELECT` for the
Step Function's `RunCTAS` state to execute. Between the purge and a successful CTAS, the
table **does not exist** — not "holds stale data", *does not exist*.

**Why it matters.**
- **There is no rollback.** Athena CTAS is not transactional and the DROP already happened.
  If the CTAS fails — an Athena timeout, a workgroup limit, a bad Silver row that breaks a
  cast — that gold table is gone *and so is last week's copy of it*, until the next Thursday
  run. That is a **7-day** outage for one failed query.
- **It fails partially.** `BuildGold` is a `Map` with `MaxConcurrency = 3` over 7 tables, so
  a failure leaves some tables rebuilt, some purged-and-empty, and some untouched. Gold is
  then internally inconsistent with no single state to reason about.
- **The window is not instantaneous.** A reader querying during the rebuild gets
  `TABLE_NOT_FOUND`, not stale data. There is no consumer today (deliberately — the grifo is
  deferred), which is exactly why this is cheap to fix *now*, before one exists.
- The S3 bytes are recoverable (versioning is on, so the purge writes delete markers) but
  only by hand, which is not a recovery procedure.

**Possible solutions, in the order they should be considered:**
1. **Blue/green location swap (recommended).** CTAS into
   `gold/<name>/run=<execution-id>/`, and only once it succeeds, point the catalog table at
   the new location (drop + re-register, or `ALTER TABLE SET LOCATION`). The old location
   keeps serving until the instant of the swap, and a failed CTAS changes nothing. A
   lifecycle rule expires old `run=` prefixes. This keeps the current one-file-per-table SQL
   and is the smallest change that actually removes the window.
2. **`INSERT INTO` an already-created table.** Create each gold table once (DDL, committed),
   then append instead of recreating. No DROP, so no window — but it needs idempotency: a
   re-run must not double-count, so it requires either delete-by-partition first or a
   dedupe key. Natural companion to PR-043 and the better end state if that PR lands.
3. **Iceberg tables (deferred, see L5).** Real atomic commits and time travel, at the cost of
   moving Gold onto a table format the rest of the stack does not use yet.
4. **Minimum viable mitigation** if neither lands soon: have the purge Lambda copy the
   current prefix to `gold/_previous/<name>/` before emptying it, and add a Step Function
   `Catch` on `RunCTAS` that restores it. Ugly, but it turns a 7-day outage into a minute.

**Do not** "fix" this by removing the purge — the purge exists because Athena CTAS refuses a
non-empty `external_location` (`HIVE_PATH_ALREADY_EXISTS`). The location has to be empty *or*
new; option 1 makes it new.

---

### Sub-PRs

**PR-042.1 — Build beside, then swap.** Option 1 above (blue/green), split out so the swap
mechanism is reviewed without the cleanup riding along. Two things to get right that the
options list does not spell out:
- `external_location` is a hardcoded literal in all seven SQL files and `purge_and_load`
  parses it back out with `_EXTERNAL_LOCATION_RE`. Whatever replaces it must keep the SQL
  file as the single source of truth for table name and location — that property is *why*
  the Lambda parses the file instead of duplicating config in Terraform.
- The three partitioned tables register partitions at CTAS time. **Verify the partitions
  resolve against the new location after the swap** — a location change on a partitioned
  table does not necessarily move its partition locations, and a table that reads empty
  after a "successful" swap is the failure mode to look for.
**Acceptance — this is the whole PR:** force a CTAS failure on one table and show the
published table still returning its previous row count.

> **PR-042.1 outcome.** Built as designed, with one deviation and one hazard worth naming.
>
> **The shape.** The Lambda grew two actions and the Map grew a state:
> `PrepareGold → RunCTAS → PromoteGold`. `prepare` rewrites the file's CREATE to build
> `<table>__stg_<run>` at `gold/<name>/run=<run>/` and touches nothing published; `promote`
> runs only after Athena succeeded and swaps the catalog with **one `glue:UpdateTable`**.
> The SQL file stays the single source of truth — both staging names are *derived* from it,
> not configured anywhere. The rendered ASL was checked with
> `aws stepfunctions validate-state-machine-definition`: `OK`.
>
> **Partitions are updated, not dropped and recreated.** `BatchUpdatePartition` for values
> the new generation shares, create for new ones, delete for ones it no longer has — in that
> order. A delete-then-create passes through a state where the table has no partitions at
> all, which is the "successful swap, empty table" failure this section warns about.
> Glue's batch APIs report per-item failures in the *response*, not as an exception, so
> those are checked and raised: ignoring them is how a swap reports success while leaving
> the table pointing half at one generation and half at another.
>
> **The deviation.** The roadmap suggested `run=<execution-id>` under the table's prefix,
> which is what was built — but it is worth writing down that this makes the staging
> location a CHILD of the location the published table currently points at. Athena reads a
> location recursively, so between the first CTAS finishing and its promote, a query on the
> old table would see the old files *and* the new ones and double-count. The window is
> seconds, it closes at promote, **it happens once ever** (afterwards the table points at a
> specific generation, not the parent), and Gold has no consumer today — which this section
> already names as why fixing B now is cheap. Staging outside the table's prefix would avoid
> it at the cost of a layout where a table's data does not live under the table's prefix.
>
> **The acceptance criterion, runnable in prod in under a minute** without breaking anything:
> invoke the Lambda alone with `{"action":"prepare", ...}` for one table and then simply do
> not run the CTAS — which is precisely the state a failed run leaves. Then query the
> published table: it still returns its previous rows. Against the pre-042.1 Lambda the same
> two steps leave the table dropped and its Parquet deleted.
>
> ### What the plan really said, measured at apply time (2026-09-20)
>
> The verification line in the commit claims `0 add, 3 change, 0 destroy`. **The real plan
> is 12 changes**, and the gap is not drift — it is two things that line was measured
> without:
>
> - **The seven `aws_s3_object.gold_sql` objects.** The same commit added a 14-line header
>   note to every `.sql` file, and those objects carry `etag = filemd5(...)`, so they were
>   always going to appear. `14 insertions, 0 deletions` each — header only, no CTAS body
>   touched, verified before applying.
> - **`extractor_lambda` + its `aws_s3_object.lambda_package`.** `lambda_package.zip` ships
>   **the whole `loteria/` package** — all 24 entries, `loteria/gold/purge_and_load.py`
>   among them. Rewriting the gold module therefore changes the extractor's
>   `source_code_hash` even though the extractor never imports it. Structural and harmless,
>   but it means *every* PR that touches *any* module under `src/loteria/` redeploys the
>   extractor. Worth knowing before reading it as a surprise.
>
> **Lesson, the same one PR-019 already paid for in the other direction:** a plan quoted in
> a commit message is a measurement of the tree at the moment it was taken, not a promise
> about the tree that gets merged. Re-measure at apply time and reconcile every line — the
> point is not the count, it is that nothing unexplained is in there.
>
> **Also stripped out of this apply, deliberately:** `make build` marked
> `aws_lambda_layer_version.loteria_deps` for replacement (`1 add, 1 destroy`) plus its S3
> object. Cause: one floating transitive, `idna 3.19 -> 3.20` — every other package in the
> layer was byte-identical. The deployed zip was restored over the rebuilt one
> (`md5 d786e490aa9dba1ea6d5223b5c5bee6a`, 942 417 bytes, matching the live `etag` and
> `source_code_size` exactly) so the apply carried 042.1 and nothing else. It is deferred,
> not avoided — it returns on the next `make build`. See **PR-046**.

**PR-042.2 — Retire old generations.** Keep the live generation plus one, so the rollback
is "re-point the catalog at the previous generation" — write that command in the runbook.
The deletion is its **own** Step Functions state, running **after** the swap, allowed to
fail without failing the run: a leaked generation costs cents, while a delete that runs
before the swap is precisely the defect 8B exists to remove. Alarm on repeated failure
instead of blocking.


## PR-043 — Incremental Gold instead of a full weekly rebuild
**Fault C.**

**The defect.** Every Thursday all 7 gold tables are rebuilt from the entire history to
incorporate **one** new sorteo. `01_gold_draw_summary.sql` scans all of
`silver_sorteos_sorteos ⋈ silver_premios_premios` to produce a table whose grain is
`numero_sorteo` — 111 of whose ~112 rows are byte-identical to last week's.

**Why it matters even though it is cheap today.**
- The work scales with **history**, not with **arrivals**. Cost and runtime grow every week
  while the input never does. At ~117k rows it is a rounding error, and that is the trap:
  nothing will signal the moment it stops being one.
- **It compounds fault B.** The longer the rebuild, the longer each table sits empty.
- Athena bills scanned bytes; a full re-scan of Silver ×7 every week is the single largest
  recurring query cost in the project, and it buys one sorteo's worth of new information.
- It is the thing a reviewer will ask about. "Why do you recompute 2024 every week?" has no
  good answer, and the honest one ("it was cheap") reads as not having thought about it.

**Recommendations — the 7 tables are not one problem, they are three:**

| Group | Tables | What to do |
|-------|--------|------------|
| **Already partitioned by `year`** | `gold_geo_winnings`, `gold_vendor_leaderboard`, `gold_time_series` | The cheapest real win. Rebuild **only the current year's partition**: `INSERT INTO` after deleting that one partition, with the `SELECT` filtered by `WHERE year = <current>`. Prior years are immutable — a sorteo never changes after it is drawn — so re-deriving them is pure waste. |
| **Append-only grain** | `gold_draw_summary` (one row per `numero_sorteo`) | The grain matches the arrival unit exactly. `INSERT INTO ... WHERE numero_sorteo NOT IN (SELECT numero_sorteo FROM gold_draw_summary)` appends just the new draws and is naturally idempotent. |
| **Global aggregates** | `gold_winning_number_frequency`, `gold_terminations`, `gold_letters_distribution` | Every row genuinely depends on the whole history (they are frequency counts). Full rebuild is *correct* here. Keep it — but write the decision down in the SQL file's header so it reads as a choice, not an oversight. These three are also small enough that PR-042's swap makes them safe. |

**Sequencing note:** this PR is much easier **after** PR-042. Option 2 there (`INSERT INTO`
a persistent table) is the same mechanism this PR needs, so doing B first means C is mostly
SQL. Doing C first means writing the incremental logic twice.

**Prompt sketch (do not run until PR-042 lands):**
```
For the four incremental tables, change sql/gold/*.sql from `DROP + CTAS` to:
  - a one-time committed CREATE TABLE (DDL only, no SELECT) under sql/gold/ddl/
  - a per-run INSERT INTO with the year/sorteo filter
Then teach src/loteria/gold/purge_and_load.py the two modes (full vs incremental) and mark
which mode each file uses in a header comment the Lambda parses — same pattern it already
uses to parse external_location and the table name, so the SQL file stays the one source
of truth.
```

---

### Sub-PRs

**PR-043.1 — Measure first, in the style of PR-020.** No behaviour change. Pull bytes
scanned, runtime and cost per CTAS from the `lottery-wg` query history, and project them at
2× and 10× the current Silver. Verify the three-group classification above against each
file's `GROUP BY` rather than against its name. Deliverable:
`docs/runbooks/PR-043-gold-incremental-spike.md`. **"Keep the full rebuild" is a valid
verdict per table** — if the machinery costs more complexity than it saves, say so with the
numbers and do not build it.

**PR-043.2 — The four incremental tables.** Only what 043.1 recommends. Two requirements
the prompt sketch above leaves implicit:
- **Idempotency comes from querying the target**, not from assuming the run is the first:
  `MAX(numero_sorteo)`, or the set of years present. Mirror the transformer's own
  `list_processed_sorteos_in_partitioned_bucket` check.
- **This collides with 042's generations, and the collision must be resolved in writing.**
  `INSERT INTO` a published generation writes into live data. Either the generation becomes
  copy-then-append, or these four tables opt out of the generation mechanism with a stated
  reason. Hand-waving it reintroduces the exact defect 8B just fixed.
Keep a `make` target that forces a full rebuild of any table — incremental pipelines drift,
and it is also the recovery path when 042.2 deletes a generation you turn out to need.

**PR-043.3 — Decide the three global aggregates.** Mostly writing: put the decision and its
numbers in each SQL file's header so the full rebuild reads as a choice. If the spike
instead recommends sourcing them from `gold_draw_summary` rather than from
`silver_premios`, that is the implementation. If anyone proposes a running-count merge, a
monthly from-scratch reconciliation **and** a test comparing incremental against full are
mandatory, not optional.


## PR-044 — `quarantine/` for rows the parser rejects
**Fault E.**

**The defect.** When the parser meets something it does not understand, it logs a warning and
moves on — `logger.warning("Skipping file with unexpected structure", ...)` in the
transformer, and the equivalent per-row skips in `src/loteria/parser/parser.py`. The row is
gone. Nothing records what it was, why it was dropped, or which sorteo it came from, and
nothing counts how many were dropped in a run.

**Why it matters.**
- **Silent data loss is the worst failure mode a pipeline has**, because every downstream
  number still looks plausible. A gold `total_premios` that is short by four rows is not
  distinguishable from a draw that had four fewer prizes.
- **PR-033 makes this sharper, not softer.** Once the DQ gate is wired, the suites will say
  *that* Silver is wrong. Without a quarantine there is nowhere to look to find out *what*
  was wrong — the offending input was discarded before it reached the layer being validated.
- The scraper outage of 2026-08 (PR-031.1) was exactly this class of problem one stage
  earlier: the site changed, a selector silently matched nothing, and the failure surfaced as
  absence rather than as an error. The lesson generalizes — absence must be recorded.

**What to build:**
```
1. A quarantine writer in src/loteria/common/ (or loteria/parser/): given the raw line/block,
   a machine-readable reason code, the sorteo number and the correlation_id, write to
   s3://<partitioned>/quarantine/dataset=<sorteos|premios>/year=<YYYY>/sorteo=<NNNN>/
   as Parquet (not .txt — it has to be queryable).
2. Replace the silent skips in parser.py and transformer.py with calls to it. The row is
   still skipped; it is now also kept.
3. Emit a CloudWatch metric `QuarantinedRows` (the PR-026 custom-metric pattern) and add a
   PR-025-style alarm: > 0 quarantined rows in a run is worth an email, because today the
   expected value is exactly zero.
4. Register the prefix as a table (crawler or CTAS) so `SELECT reason, count(*)` works in
   Athena. A quarantine nobody can query is a folder.
5. Add the reason-code vocabulary to the runbook — free-text reasons make step 4 useless.
```

**Design note:** quarantine is **not** a dead-letter queue to be replayed automatically. The
whole point is that a human reads it and decides whether the parser or the source changed.
Resist adding a reprocessing path in this PR.

---

### Sub-PRs

**PR-044.1 — Make the loss visible (no new storage).** Ship this before the quarantine
store; it is small and it produces the number the alarm needs.
`process_body` (`src/loteria/parser/parser.py:121-123`) drops unmatched lines into an
`else` that logs at **DEBUG** — Glue does not run at DEBUG, so the line vanishes, and
`premios_count` is then reported with no denominator. Return `(rows, rejects)` instead of a
bare list, log each drop at **INFO** with the truncated line and a reason code, and emit
`lines_total` / `lines_parsed` / `lines_rejected` per run.
**Alarm on the rate, not the count.** The section above assumes the expected value is
exactly zero; run the parser over the whole archived `raw/` corpus first and find out. A
draw with a couple of odd footer lines is normal, and an alarm that fires every Thursday is
the canary-that-always-skips failure from PR-031 wearing a third hat. **Acceptance:** the
measured baseline across all archived draws is in the PR description, and the threshold is
derived from it — not guessed.

**PR-044.2 — Persist the rejects.** The quarantine writer, the reason-code vocabulary, the
catalog registration, and the `> baseline` alarm. One constraint worth stating out loud:
**a rejected line must never fail the run by itself** — the rate alarm is what escalates.
A hard failure here turns one odd footer line into a missed week of ingestion. The DQ gate
reading the quarantine count is a follow-up, deliberately not wired here.


## PR-045 — Lineage columns in Silver
**Fault F.**

**The defect.** Silver Parquet carries only business columns. There is no `ingested_at`, no
`run_id`, no source-file reference. PR-018 already threads a `correlation_id` through the
**logs** of every stage (extractor → transformer → gold), and `glue_zip_main.py` bridges it
into the Glue job's environment — but it never reaches the **data**.

**Why it matters.**
- When a gold table looks wrong, the first question is "which run produced these rows?" Today
  that is answered by correlating S3 object timestamps against CloudWatch by hand.
- **Reprocessing is unsafe without it.** If a sorteo ever has to be re-scraped and rewritten
  (the 2026-08 outage nearly forced this), there is no way to tell the old rows from the new
  ones after the fact.
- It is the cheapest possible moment to add this. Backfilling a column across 222 existing
  Parquet files later means rewriting all of them; adding it now means new files have it and
  a single optional backfill job handles the rest.
- It makes the PR-033 gate stronger for free: `expect_column_values_to_not_be_null` on
  `run_id` catches "something wrote Silver outside the pipeline", which nothing currently can.

**What to add:**
```
Columns on both silver datasets (sorteos + premios):
  - ingested_at   timestamp, UTC, the moment the transformer wrote the file
  - run_id        string, the PR-018 correlation_id (= the Step Function execution name)
  - source_key    string, the raw/ S3 key the row was derived from

1. Set them in src/loteria/transformer/transformer.py right before the Parquet write.
2. Add the three columns to the PR-032 suites (not-null on all three) and re-sync the
   committed JSON with `make dq-sync`.
3. The silver crawlers pick the new columns up on the next run — but confirm, because a
   schema change on an existing table is exactly the case where a crawler can create a
   second table instead of evolving the first.
4. Optional follow-up, separate PR: a one-shot backfill for the 222 existing files, writing
   a sentinel run_id like "backfill-PR-045" so pre-lineage rows are identifiable as such.
```

**Watch out:** the gold CTAS files `SELECT` explicit columns, so new Silver columns will not
leak into Gold by accident — verify that when writing this, and decide deliberately whether
`gold_draw_summary` should carry the `run_id` that built it (recommended: yes, it is the only
way to trace a gold row back to a pipeline run).

---

### Sub-PRs

**PR-045.1 — Write the columns.** The three columns above, plus `parser_version` (a
constant bumped by hand when the parse changes shape — it is what makes a reprocessing
decision answerable later). Two corrections to the prompt above, both found while auditing
it:
- **Do not make the suite expectations unconditional not-null.** The suites validate the
  whole dataset, which includes the 222 pre-lineage files, so `not_null` on `run_id` goes
  **red on day one against real data** — the fails-on-day-one trap PR-032 spent a paragraph
  avoiding. Scope the expectation to rows where the column is present, or gate it on a
  `parser_version` floor.
- **Do not backfill as part of this PR.** A backfilled `ingested_at` is a lie and a
  fabricated `run_id` is worse than a null one; NULL correctly means "written before
  lineage existed". Keep the sentinel-backfill idea as the separate PR the section already
  proposes, and decide it on its own merits.
The "watch out" above is already true and worth pinning: **no file in `sql/gold/` uses
`SELECT *`**, so new Silver columns cannot leak into Gold. Add the test that asserts it —
that is what keeps the *next* Silver column safe.

**PR-045.2 — Make lineage queryable.** A view (cheaper than an eighth gold table for what
is metadata, not analytics): one row per `(run_id, dataset)` with rows written, min/max
`ingested_at`, and the source keys. Then answer, in the runbook with real output pasted in,
the question this sub-phase exists for: *"sorteo 3134 looks wrong — which run wrote it,
from which raw file, and what else did that run write?"* as a single Athena query.


## PR-046 — Pin the transitive dependencies so `make build` is reproducible
**Found at PR-042.1's apply, 2026-09-20. Not an audit fault — a build defect.**

**The defect.** `requirements/extractor.txt` pins its two direct dependencies
(`beautifulsoup4==4.13.4`, `requests==2.32.4`) and **nothing else**. The seven transitive
packages that actually land in the layer — `certifi`, `charset_normalizer`, `idna`,
`soupsieve`, `typing_extensions`, `urllib3` — float. `requirements/glue.txt` and
`requirements/dq.txt` have the same shape.

**Why it matters, concretely.** `make build` must run before any `plan`, because
`filemd5`/`filebase64sha256` read the zips at plan time (PR-019). So every plan in this repo
is taken against a layer that was resolved *that day*. On 2026-09-20 that meant PyPI's
`idna 3.20` silently replaced `3.19`, `aws_lambda_layer_version` was marked **for
replacement**, and PR-042.1's plan arrived as `1 add, 13 change, 1 destroy` instead of
`0 add, 12 change, 0 destroy`. The unrelated change was larger and scarier-looking than the
reviewed one.

Three costs, in order of how much they hurt:
1. **It buries the PR's real diff.** A reviewer reconciling a plan has to separate the
   change under review from build noise, every single time. That is exactly the failure
   mode PR-023 already recorded when `make build` churn masked its own plan, now with a
   second and more persistent cause.
2. **It ships untested code.** A patch bump nobody chose, nobody read and no test covered
   rides into prod attached to an unrelated apply. `idna` is low-risk; the mechanism is not.
3. **A build is not reproducible.** Rebuilding last month's commit does not reproduce last
   month's artifact, so "is the deployed zip current?" stops being answerable by hash —
   which is the check PR-019 established and PR-041.1 depended on.

**The fix.** Compile a fully-pinned lock per runtime (`pip-compile` / `uv pip compile`,
hashes included) and have the build scripts install from the lock, keeping the hand-written
`.txt` as the input. Then a layer hash changes only when someone deliberately recompiles.

**Sequencing.** Do it **after** PR-042.1 is applied and verified, not before — landing it
first would put a new layer into the very apply this PR exists to keep clean. The first
recompile legitimately bumps the layer; that is its own plan, reviewed on its own.

**Acceptance:** `make build` run twice on different days produces byte-identical zips, and
a `plan` immediately after a `build` shows **no** layer diff.

> **Owed from 2026-09-20:** the rebuilt layer carrying `idna 3.20` was set aside rather than
> applied, and the deployed `idna 3.19` zip was restored in its place. That bump is still
> owed — it should land as the first recompile under this PR, not as a stray.

---

# Open later (deferred decisions)

These are deliberately *not* on the path to "hiring-manager-ready". Capture once, revisit later.

| ID | Topic | Notes |
|----|-------|-------|
| L1 | Two AWS accounts (dev + prod) for cost separation | Owner prefers separate accounts over Terraform envs. Implement only after the single-account stack is solid. Use AWS Organizations + SCP or run as two independent accounts and rely on per-account billing. |
| L2 | dbt-core on Athena | If Gold logic outgrows raw CTAS, migrate to dbt for lineage + tests + docs. |
| L3 | ML / forecasting feature | Predict winning-number distribution, vendor performance. Showcases MLOps later. |
| L4 | QuickSight asset-as-code | The TF provider for QS is rough. Snapshot dashboard JSON until it improves. |
| L5 | Iceberg / Apache Hudi for Silver | If we ever need MERGE/UPSERT semantics. |
| L6 | Migrate transform off Python Shell (→ Spark `glueetl` or Ray) | The only path to Python 3.10+ / a "Glue 4.0/5.0" runtime — Python Shell caps at 3.9 (see PR-020 outcome). Requires rewriting `loteria.transformer` to PySpark, a new DPU/billing model, and reworked IAM/logging. AWS now publishes a "Migrate from Python shell jobs" guide, so this is the sanctioned long-term direction. Do only when a concrete need (scale, a 3.10-only lib) appears. |

---

# PR Tracker

Update as work lands. Statuses: `todo`, `in-progress`, `merged`, `blocked`, `dropped`.

| PR | Title | Status | Link |
|----|-------|--------|------|
| 001 | Repo hygiene baseline | merged | [PR #2](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/2) |
| 002 | Inventory + protect prod buckets | merged | [PR #3](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/3) |
| 003 | Bootstrap remote state backend | merged | [PR #4](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/4) |
| 004 | Move state to remote backend | merged | [PR #5](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/5) |
| 005 | Import buckets + prevent_destroy | merged | [PR #6](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/6) |
| 006 | Module skeleton + root caller | merged | [PR #7](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/7) |
| 007 | Migrate `storage` module | merged | [PR #8](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/8) |
| 008 | Migrate `network` module | merged | [PR #9](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/9) |
| 009 | Migrate `iam` module | merged | [PR #10](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/10) |
| 010 | Migrate `etl-lambda` module | merged | [PR #11](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/11) |
| 011 | Migrate `etl-glue` module | merged | [PR #12](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/12) |
| 012 | Migrate `catalog` + `orchestration`, kill dup EventBridge | merged | [PR #13](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/13) |
| 013 | Codify Lake Formation | merged | [PR #14](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/14) |
| 014 | Observability placeholder + SNS | merged | [PR #15](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/15) |
| 015 | SageMaker optional, delete old TF folder | merged | [PR #16](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/16) |
| 016 | `src/` consolidation | merged | [PR #18](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/18) |
| 017 | Parameterize hard-coded config | merged | [PR #19](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/19) |
| 018 | Structured JSON logging | merged | [PR #20](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/20) |
| 019 | Lambda Layer for deps | merged | [PR #21](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/21) |
| 020 | Glue runtime spike (stay on Python Shell 3.9) | merged | [PR #23](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/23) |
| 021 | Gold SQL files | merged | [PR #24](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/24) |
| 022 | Wire Gold into Step Function | merged | [PR #25](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/25) |
| 023 | Log retention | merged | [PR #26](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/26) |
| 024 | CloudWatch dashboard | merged | [PR #27](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/27) |
| 025 | Alarms | merged | [PR #29](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/29) |
| 026 | Scraper HTTP status metric | merged | [PR #28](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/28) |
| 026.1 | **Fix `startCrawler` ↔ gold CTAS race** (correctness defect — gold can silently miss the newest sorteo) | merged | [PR #30](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/30) |
| 027 | S3 object-count emitter (optional) | merged | [PR #31](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/31) |
| 028 | SNS email subscription | merged | [PR #32](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/32) |
| 029 | pytest skeleton + parser tests | merged | [PR #34](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/34) |
| 030 | Transformer tests with moto | merged | [PR #35](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/35) |
| 031 | Scraper contract canary | merged | [PR #36](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/36) |
| 031.1 | **Restore the scraper** (outage 2026-08-20 → 2026-08-27: Cloudflare profile + site redesign moved the prize list + no retries) | applied + merged | [PR #42](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/42) |
| 032 | GE Silver suite | merged | [PR #37](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/37) |
| 033 | DQ gate in Step Function | **applied + verified** (2026-09-16 apply; both directions exercised 2026-09-16/20) | [PR #46](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/46) |
| 033.1 | **Fix what the first real runs exposed** — 22-min startup vs a 30-min timeout, and a per-job log group that stayed empty | applied + merged (2026-09-20) | [PR #49](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/49) |
| 033.2 | **The fix for 033.1's defect B did not work in prod** — the CloudWatch handler fed its own boto3 chatter back into itself and disabled itself; group had a stream and zero events | **applied + verified** (2026-09-20) | [PR #50](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/50) |
| 034 | GitHub Actions CI | merged | [PR #45](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/45) |
| 035 | **Coverage ratchet** — 70 → 98 (roadmap asked 85; the convention is the number the suite achieves). Rescued from the stranded branch + the extractor rebuilt for the post-redesign markup | in-progress | — |
| 035.1 | **Three defects the coverage work found** — the extractor's dead idempotency guard, the unanchored draw-date regex, and one malformed header killing the whole transform | todo | — |
| 036 | README rewrite | todo | — |
| 037 | Diagrams in draw.io | todo | — |
| 038 | ADRs | todo | — |
| 039 | Fill in Makefile | todo | — |
| 040 | `.envrc.example` + final polish | todo | — |
| *Phase 8 — work in the order below (**8A → 8E**), not by number.* | | | |
| 041 | **8A** · Retire the `simple` bucket (fault A) — `.1` stop writes · `.2` strip config · `.3` tear down *(irreversible)* | `.1` in-progress · `.2`/`.3` todo | — |
| 042 | **8B** · Atomic Gold publication (fault B) — `.1` build beside + swap · `.2` retire generations | `.1` in-progress · `.2` todo | — |
| 045 | **8C** · Lineage columns in Silver (fault F) — `.1` write them · `.2` make them queryable | todo | — |
| 044 | **8D** · `quarantine/` for rejected rows (fault E) — `.1` make the loss visible · `.2` persist the rejects | todo | — |
| 043 | **8E** · Incremental Gold (fault C) — `.1` measure · `.2` incremental tables · `.3` decide the aggregates | todo | — |
| 046 | Pin transitive deps so `make build` is reproducible (found at 042.1's apply) | todo | — |
