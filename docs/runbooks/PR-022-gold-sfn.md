# PR-022 — Wire the Gold layer into the Step Function

Turns the 7 CTAS files authored in PR-021 into an automated Bronze → Silver → **Gold**
run. No manual Athena-console clicks after this lands.

## What changed

| Piece | File | Change |
|---|---|---|
| SQL upload | `terraform/modules/orchestration/main.tf` | `aws_s3_object.gold_sql` uploads `sql/gold/*.sql` → `s3://<partitioned>/sql/gold/` |
| Purge Lambda | `src/loteria/gold/purge_and_load.py` + `main.tf` | single-file, boto3-only Lambda zipped by `archive_file` |
| Gold states | `terraform/modules/orchestration/main.tf` | `RunSorteosCrawler` → `PrepGold` (Pass) → `BuildGold` (Map) |
| SFN IAM | `terraform/modules/iam/main.tf` | athena + glue-table + gold-S3 + invoke-purge grants added to `sfn_execution_policy` |
| Purge IAM | `terraform/modules/iam/main.tf` | new `gold_purge_lambda` role + scoped S3/Glue policy |
| Wiring | `terraform/main.tf` | new inputs threaded to `iam` + `orchestration` |
| Provider | `terraform/provider.tf` | `hashicorp/archive ~> 2.4` added |

## Why a purge Lambda (the two constraints that force it)

Each `sql/gold/NN_*.sql` file holds **two** statements: `DROP TABLE IF EXISTS …;` then
`CREATE TABLE … AS SELECT …;`. Athena cannot run that file as-is:

1. **Athena `StartQueryExecution` runs ONE statement per call.** So the Lambda performs the
   DROP itself via `glue:DeleteTable` (idempotent — a missing table is fine) and returns
   only the `CREATE TABLE` statement for the Athena task.
2. **CTAS fails onto a non-empty `external_location`** (`HIVE_PATH_ALREADY_EXISTS`). The
   PR-021 manual runs already wrote Parquet under `gold/<name>/`, so the Lambda empties
   that prefix first. The bucket has versioning on (PR-002/005), so the deletes leave
   delete-markers — **history is retained**, the location just reads empty for the CTAS.

The Lambda parses the table name and `external_location` **from the SQL file**, so the file
stays the single source of truth (no duplicated config in Terraform).

## The state machine, after this PR

```
RunExtractorLambda → RunTransformerGlueJob → RunPremiosCrawler → RunSorteosCrawler
  → PrepGold (Pass: inject the plan-time list of gold SQL keys)
  → BuildGold (Map, MaxConcurrency=3), per gold table:
        PurgeAndLoad (Lambda: drop table + empty prefix, returns CREATE stmt)
        → RunCTAS (athena:startQueryExecution.sync, WorkGroup=lottery-wg)
```

The Map's item list is baked at **plan time** via `fileset("sql/gold", "*.sql")` — the
machine never lists S3 at runtime. The 7 gold tables all read only `silver_*` (none depends
on another gold table), so parallel execution is safe.

## No gold crawler (roadmap step 4 skipped — on purpose)

Athena CTAS `CREATE TABLE` registers each `gold_*` table + its partitions in the catalog
directly, and the build fully recreates every table each run — so the catalog is always
current when the CTAS finishes. A crawler would re-scan already-registered data for no
benefit. See `terraform/modules/catalog/README.md`. Revisit only if gold ever switches to
`INSERT INTO` (append) semantics.

## Deploy

```bash
cd terraform
terraform init      # picks up the new hashicorp/archive provider
terraform plan      # expect: +gold_sql objects, +gold-purge Lambda + role/policy,
                    #         ~sfn_execution_policy, ~state machine definition
terraform apply
```

Then trigger one full run (or wait for the Thursday cron) and confirm the `gold_*` tables
are queryable:

```bash
aws stepfunctions start-execution \
  --state-machine-arn "$(terraform output -raw ... )"   # or start from the console
# after it completes:
aws glue get-tables --database-name lottery_santalucia_db \
  --query "TableList[?starts_with(Name,'gold_')].Name"
```

## ⚠️ Known limitation — crawler completion timing (follow-up candidate)

`RunPremiosCrawler` / `RunSorteosCrawler` use `aws-sdk:glue:startCrawler`, which is
**fire-and-forget** (the pre-existing PR-012 behavior). The Step Function does **not** wait
for the silver crawlers to reach `READY` before `BuildGold` starts. Consequences:

- The silver *tables* already exist from prior runs, so the CTAS JOINs still succeed — it
  does **not** hard-fail.
- But if a crawler is still mid-run, the newest sorteo's partition may not be registered
  yet, so that run's gold can be **stale by one sorteo**. It self-corrects the following
  week.

If guaranteed-fresh gold matters, a follow-up should insert a `GetCrawler`-poll wait loop
(`State != RUNNING`) after each `startCrawler`, or switch to a crawler-completion callback.
Left out of PR-022 to keep it atomic and aligned with the roadmap's sequencing.

## Lake Formation note

The database is in **hybrid access mode** (`enable_iam_allowed_principals_compat = true`,
PR-013), so the IAM grants added here are sufficient for the SFN role to create the gold
tables — no Lake Formation grants for the SFN role are required. If that compat flag is
ever disabled (full LF enforcement), the SFN role will additionally need LF
`CREATE_TABLE` on the database + `DATA_LOCATION_ACCESS` on the `gold/` path, and the
purge Lambda role will need LF `DROP`. See the `lake-formation` module + the
LF-gotchas note.
