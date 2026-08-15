# Roadmap — Loteria Santa Lucia, "Hiring Manager Ready"
**Owner:** Angel Hernandez
**Companion doc:** [`DoD.md`](./DoD.md) (vision + locked decisions)
**Last updated:** 2026-06-28

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

> **Notes from executing it (2026-08-15):** the gate is in, the rendered ASL validates clean
> against the Step Functions API, and `terraform plan` is 5 to add / 3 to change / 0 to
> destroy. See `docs/runbooks/PR-033-dq-gate.md`.
>
> - **🚨 THE PROMPT'S JOB TYPE IS IMPOSSIBLE, as PR-032 predicted.** "A Python Shell job that
>   pip-installs great-expectations" cannot work: GX 1.x needs Python ≥ 3.10 and Python Shell
>   supports only 3.6/3.9. Re-verified against the current AWS docs in this PR — Python 3.11
>   arrived with Glue 5.0 but **only for Spark jobs**. So the DQ job is `glueetl` on Glue 5.0.
>   It never creates a SparkContext; the cluster is the price of the interpreter version.
>   Cost consequence worth stating: the pythonshell transformer runs at `max_capacity = 1`
>   DPU, while a Glue 5.0 ETL job has a **floor of 2 workers**. There is no smaller shape.
> - **The Fail state cannot publish.** The roadmap's "a Fail state that publishes to SNS" is
>   two states: `NotifyDQFailure` (Task, `sns:publish`) then `DQFailed` (Fail). The Fail state
>   type has no integration.
> - **⚠️ Gating the states with `condition ? {...} : {}` does not compile.** Terraform requires
>   both branches of a conditional to have the same type, and an ASL state map is
>   heterogeneous by construction — a Task has Resource/Parameters/Catch, a Fail has
>   Error/Cause, and they share no attributes, so it fails with *"the 'true' value includes
>   object attribute "DQFailed", which is absent in the 'false' value"*. The gate is applied
>   to a **JSON string** and `jsondecode`d instead, which sidesteps type unification.
>   Verified: with `enable_silver_dq = false` the rendered definition is **byte-identical to
>   the deployed one**, so the kill switch really is a no-op.
> - **⚠️ SNS topic ARN is built from name + region + account, not read from
>   `module.observability`.** That module already consumes `module.orchestration
>   .state_machine_arn`, so the reverse reference closes a **module cycle** Terraform refuses
>   to graph. Same technique PR-023 used for the vended-logs group ARN.
> - **The alert message is the deliverable, not the alarm.** Step Functions puts Glue's
>   `ErrorMessage` into the SNS body verbatim, and for a Python error that is the exception's
>   string — so `glue_dq_main.py` raises with a summary naming the suite, expectation and
>   column. Offending *values* are deliberately excluded (a failing column can be full of
>   vendor names, and this lands in an inbox); the samples stay in the Glue log.
> - **`States.Format` escaping was avoided rather than solved.** It delimits its literal with
>   single quotes and uses `{}` as placeholders, so the message text deliberately contains no
>   apostrophes and no braces. An escaping bug here is only discovered when the alert fires —
>   the one moment it has to work.
> - **This job gets its own log group**, `/aws-glue/jobs/loteria-silver-dq-prod`, via the
>   Spark-only `--continuous-log-logGroup`. Not just tidier: the account-wide Spark groups
>   `/aws-glue/jobs/{output,error,logs-v2}` **already exist and already carry another
>   project's workload**, so the `manage_shared_glue_log_groups` escape hatch — justified for
>   pythonshell by this being the account's only such job — does not extend to Spark.
> - **A dedicated read-only role**, not the transform job's. A component whose purpose is to
>   *judge* the data should not be able to change it, nor carry the scraper's Secrets Manager
>   access. No `PutObject`, no `DeleteObject`, `GetObject` scoped to `silver/*`, and
>   `AWSGlueServiceRole` deliberately not attached (it grants `glue:*` plus S3 write).
>   Note `s3:ListBucket` is a bucket-level action and cannot take a prefixed ARN — the
>   scoping has to come from an `s3:prefix` condition.
> - **Deliberately NOT done: running DQ in parallel with the crawlers.** The job reads Silver
>   Parquet straight from S3, not through the catalog, so it has no data dependency on
>   `RunSilverCrawlers` and could overlap with it. Kept sequential because the gate's job is
>   to stand between Silver and Gold, and a linear chain is far easier to read in the console
>   when diagnosing a blocked run. The saving is minutes, once a week.
> - **`format_report`/`summarize_failures` moved out of `scripts/run_dq.py` into
>   `loteria/dq/runner.py`**, because the Glue entry point needs the identical rendering.
>   Left duplicated, a terminal run and an email could describe the same failure differently.
> - Coverage ratchet 56 → **57**.

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

> **Notes from executing it (2026-08-15):** six jobs in `.github/workflows/ci.yml`. Every
> gate was RUN before being wired in — three of the six would have been red on arrival.
>
> - **`scraper-canary.yml` was NOT recreated.** PR-031 already shipped it, on a Wednesday
>   cron rather than the prompt's Sunday (a Sunday run lands in the Cloudflare waiting-room
>   window the Thursday pipeline move exists to dodge). Recreating it would have clobbered
>   that. PR-031's note called this out in advance and it was honoured.
> - **⚠️ `ruff check .` was red on arrival: 39 errors, plus 8 files `ruff format` wanted to
>   rewrite.** Not a regression — pre-commit passes ruff only the CHANGED files, so the repo
>   had never been linted in full. Every finding was in `notebooks/` or `miscellaneous/`, and
>   none in `src/`, `tests/` or `scripts/`. Both directories are now `extend-exclude`d rather
>   than reformatted: notebooks are EDA (rewriting their JSON wholesale buys nothing, and
>   nbstripout already owns their hygiene) and `miscellaneous/` is one-off scripts nothing
>   imports or deploys. `ruff check .` now covers exactly the code that runs in AWS.
> - **⚠️ checkov reports 71 failures against the existing infrastructure**, mostly deliberate
>   choices (SSE-S3 rather than a KMS CMK, no access logging on a personal project). Shipping
>   that as a blocking gate would make every PR red from day one — the failure this repo has
>   now written down three times. So `terraform/.checkov.baseline` captures today's findings
>   and CI fails only on NEW ones: a ratchet, exactly like `--cov-fail-under`. Verified it
>   exits 0 against its own baseline.
> - **Trivy instead of tfsec.** Aqua has folded tfsec into Trivy — same Terraform engine,
>   still maintained — and wiring a new CI to a tool its authors have stopped developing is
>   not a defensible start. It runs **non-blocking with a SARIF upload** to the Security tab,
>   because unlike checkov its finding volume could not be measured here (the release
>   download is blocked in this environment). Shipping a blocking gate whose output nobody
>   has looked at is precisely the mistake the checkov baseline exists to avoid. Promote it
>   once the volume is known.
> - **bandit found 5, all false positives for these runtimes, and all resolved rather than
>   baselined** — so it blocks with no exemption file, and a new finding is a real red. One
>   was `DEFAULT_SECRET_NAME` (a secret's NAME, not its value); four were `/tmp` paths, which
>   in Lambda and Glue are per-execution-container and the only writable filesystem there is.
> - **⚠️ Gotcha: bandit scans comment TEXT for its suppression token.** The first attempt at
>   documenting the suppressions quoted the marker inside the explanatory comment — which
>   turned the explanation itself into a suppression and silently disabled the check. The
>   comments now spell it as "B108" instead of writing it out. (Bandit also emits a spurious
>   "nosec encountered, but no failed test" warning for two of the f-string paths; removing
>   those markers demonstrably re-reds the run, so they stay.)
> - **The coverage threshold is deliberately NOT restated in CI.** The prompt says "fail
>   under 70%, matches pyproject", but pyproject carries a ratchet (57), not a target.
>   Hardcoding 70 would fail every PR today; duplicating the number would guarantee drift.
>   `pytest` reads it from `addopts`, which is the single source of truth.
> - `pip install -e '.[dev]'` works despite `[tool.uv] package = false` (that setting is
>   uv-only), so the dev extra stays the one place test dependencies are declared. Verified
>   in a clean venv: 149 passed.
> - `terraform/bootstrap` is a **separate root module** and gets its own init + validate via
>   a matrix; validating only `terraform/` would leave the state-backend stack unchecked.
> - CI needs **no AWS credentials at all** — `init -backend=false` means nothing in the
>   workflow can reach the real account.
> - `build-artifacts` now builds four artifacts, not the prompt's three: PR-033 added the
>   Silver DQ job script and its library zip.

## PR-035 — Bump coverage gate
**Prompt:**
```
Ratchet pyproject.toml's --cov-fail-under from 70 to 85. Add tests as needed to clear the bar (focus on parser + transformer edge cases).
```

> **Notes from executing it (2026-08-15):** **98.45%**, 257 tests (up from 149). The gate is
> set to **98**, not 85 — see below.
>
> - **The prompt's focus is stale.** It says "focus on parser + transformer edge cases", but
>   parser.py was already at 100% (PR-029) and transformer.py at 86% (PR-030). The 42 points
>   actually missing were four modules sitting at **0%**: `extractor/scraping.py` (89
>   statements), `gold/purge_and_load.py` (61), `observability/object_count.py` (45) and
>   `common/metrics.py` (20). Those got the work. The transformer edge cases the prompt asks
>   for were done too, and found a real gap (below).
> - **The gate is 98, not the roadmap's 85.** This file's own convention, written down in
>   `pyproject.toml` since PR-029, is that the number sits at what the suite ACHIEVES — an
>   85 gate on a 98.45 suite leaves 13 points of silent regression room, which is the
>   opposite of a ratchet. 85 was a floor and it is comfortably met. The four modules went to
>   ~100% rather than to "just enough", because stopping at exactly 85 would have meant
>   choosing which of them to leave untested for no reason.
> - **⚠️ FOUND A DEFECT while testing the extractor.** The draw-date regex is
>   `FECHA DEL SORTEO:\s*([\d/]+)` — an unanchored character class. On a malformed date like
>   `01/06/20XX` it matches the *prefix* `01/06/20`, so the year parses cleanly as `20` and
>   the draw is filed under `raw/year=20/`. The `except (ValueError, IndexError)` fallback to
>   `"unknown"` never fires, because nothing raised — those two lines are **unreachable dead
>   code today**. A partition named `year=unknown` is greppable; `year=20` looks like real
>   data and the crawler registers it without complaint. **Not fixed here on purpose**: this
>   is a coverage PR, and changing the extractor's parsing alters what the weekly production
>   run does for a case the site has never produced (all 111 real captures are `dd/mm/yyyy`).
>   The fix is to anchor the pattern to `\d{2}/\d{2}/\d{4}`. Documented in a test named
>   `..._DEFECT` whose assertion fails the day someone fixes it.
> - **Transformer edge case that had never run: the reintegros padding loop.** The header
>   regex accepts `REINTEGROS 3` (one value), which splits into one column while the Silver
>   schema is fixed at three. Every real capture has exactly three, so the `while` that pads
>   had never executed. Without it the transform dies at `reintegro_split[1]` — after reading
>   the raw file, before writing anything — with a traceback pointing at pandas rather than
>   at the site publishing a short header.
> - **`main()` is now tested**, which required opting out of PR-030's conftest stub (it makes
>   `getResolvedOptions` RAISE on purpose, so a test wandering in gets a loud TypeError rather
>   than a silently empty options dict). Worth it: the four argument names are the contract
>   with `terraform/modules/etl-glue`'s `default_arguments`, and renaming one there breaks
>   nothing locally while killing the weekly run at startup. The tests also pin the
>   split-brain risk — `transform()` READS its bucket from an argument but WRITES to module
>   globals, so a `main()` that failed to override them would read one bucket and write to
>   another.
> - **The gold-purge Lambda was the most dangerous untested code in the repo** — it
>   hard-deletes every object *version* under a prefix. Two of its tests exist purely to pin
>   blast radius: a sibling gold prefix survives, and `silver/` survives. Silver is the one
>   layer that cannot be rebuilt from anything but a re-scrape of a site that only publishes
>   the latest draw.
> - **The 10 statements left uncovered are documented dead ends, not gaps**, and each is
>   listed in `pyproject.toml`: the unreachable year-parse `except` above, a pagination guard
>   in `_empty_prefix`, the `else` for a header with no REINTEGROS at all (the parser raises
>   before returning one), and the entry-point shims.
> - The extractor's HTML fixtures are deliberately minimal and do NOT try to mirror
>   loteria.org.gt. Pinning the real selectors is PR-031's live canary's job; what these
>   tests pin is what the extractor *does* with a page — which branch it takes, what it
>   writes, where it uploads it — which a live test cannot check without polluting prod.
> - Coverage ratchet 57 → **98**. The plan's coverage arc (PR-029 → PR-035) is now closed.

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
| 032 | GE Silver suite | in-progress | [PR #37](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/37) |
| 033 | DQ gate in Step Function | in-progress | [PR #38](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/38) |
| 034 | GitHub Actions CI | in-progress | [PR #39](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/39) |
| 035 | Coverage ratchet to 85% | in-progress | — |
| 036 | README rewrite | todo | — |
| 037 | Diagrams in draw.io | todo | — |
| 038 | ADRs | todo | — |
| 039 | Fill in Makefile | todo | — |
| 040 | `.envrc.example` + final polish | todo | — |
