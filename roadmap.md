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

## PR-026 — Scraper response-code custom metric
**Prompt:**
```
In src/loteria/extractor/scraping.py, after each fetch_via_proxy call, emit a CloudWatch custom metric "ScraperHttpStatus" with dimension StatusCode=<code>. Use boto3 cloudwatch.put_metric_data with a 1-count value.
Emit the status BEFORE raising on non-200, so a failed proxy call (401/402/429 etc.) still produces a metric data point to alarm on.
Update the dashboard from PR-024 to include this metric.
Update IAM in etl-lambda module to allow cloudwatch:PutMetricData.

NOTE: this metric is what PR-025's ScrapeDo_Failed alarm watches. Rationale: scrape.do is a third-party proxy used on the FREE TIER — there is no guarantee how long it stays free. When the free plan lapses or the quota is exceeded, the proxy returns auth/quota/rate-limit codes (401/402/429) and the weekly scrape silently degrades to "Lambda error." A scrape.do-specific alarm gives an early, unambiguous heads-up (e.g. "start paying / swap proxy") instead of a generic failure.
```

## PR-027 — (Optional) S3 object-count emitter
**Prompt:**
```
Tiny scheduled Lambda (EventBridge cron every 1 hour) that runs:
  for prefix in ["raw/", "silver/", "gold/"]:
    count = sum(1 for _ in s3.list_objects_v2_paginated)
    cloudwatch.put_metric_data(MetricName="ObjectCount", Dimensions=[{"Layer": prefix}], Value=count)
Add to terraform/modules/observability/ as a sub-module or new aws_lambda_function. Skip if the dashboard from PR-024 already feels rich enough.
```

## PR-028 — Wire SNS email subscription via tfvars
**Prompt:**
```
Add `alert_email = "quehongosrojos@gmail.com"` to terraform.tfvars.example.
Document that the owner must confirm the SNS email subscription in their inbox after first apply.
```

---

# Phase 5 — QA / Testing (the showcase)

## PR-029 — pytest skeleton + first parser unit tests
**Prompt:**
```
1. Create tests/ with tests/unit/, tests/integration/, tests/fixtures/.
2. Capture 3 real .txt files from raw/ (anonymize vendor names: replace with VENDOR_001..N) and store under tests/fixtures/sorteos/.
3. Write tests/unit/test_parser.py covering:
   - split_header_body: HEADER/BODY found correctly; ValueError on malformed input
   - process_header: every field extracted; correct types; raises on missing fields
   - process_body: count of premios matches expected; "NO VENDIDO" sets vendido_por correctly
   - split_vendido_por_column: yields vendedor/ciudad/departamento; handles ciudad-only rows
4. Configure pytest in pyproject.toml: --cov=src/loteria --cov-fail-under=70 (will ratchet up).
5. Wire `make test` to `pytest -v`.
```

## PR-030 — Transformer unit tests with moto
**Prompt:**
```
Write tests/unit/test_transformer.py:
- Use moto's mock_s3 to stand up fake partitioned + simple buckets.
- Upload a fixture .txt under raw/year=2024/sorteo=3046/.
- Run transformer.transform(...) against the fake buckets.
- Assert: silver parquet files appear at the expected key, schema matches the canonical one, dtypes correct, year partition derived correctly.
- Add an edge-case test for the "Invalid fecha_sorteo" path (it should raise ValueError).
```

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

## PR-033 — DQ gate in Step Function
**Prompt:**
```
After the silver crawlers succeed and before the Gold CTAS map state, add:
  RunSilverDQ state that triggers an aws_glue_job (new) "loteria-silver-dq" — a Python Shell job that pip-installs great-expectations and runs the suites from PR-032.
If DQ fails, transition to a Fail state that publishes to the SNS alerts topic with the failure details. Gold is NOT built when DQ fails.
```

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

## PR-035 — Bump coverage gate
**Prompt:**
```
Ratchet pyproject.toml's --cov-fail-under from 70 to 85. Add tests as needed to clear the bar (focus on parser + transformer edge cases).
```

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
| 023 | Log retention | in-progress | [PR #26](https://github.com/AngelDHackerman/Lottery_End_To_End_ETL_Data_Pipeline/pull/26) |
| 024 | CloudWatch dashboard | todo | — |
| 025 | Alarms | todo | — |
| 026 | Scraper HTTP status metric | todo | — |
| 027 | S3 object-count emitter (optional) | todo | — |
| 028 | SNS email subscription | todo | — |
| 029 | pytest skeleton + parser tests | todo | — |
| 030 | Transformer tests with moto | todo | — |
| 031 | Scraper contract canary | todo | — |
| 032 | GE Silver suite | todo | — |
| 033 | DQ gate in Step Function | todo | — |
| 034 | GitHub Actions CI | todo | — |
| 035 | Coverage ratchet to 85% | todo | — |
| 036 | README rewrite | todo | — |
| 037 | Diagrams in draw.io | todo | — |
| 038 | ADRs | todo | — |
| 039 | Fill in Makefile | todo | — |
| 040 | `.envrc.example` + final polish | todo | — |
