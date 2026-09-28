# Module: `catalog`

Glue Data Catalog database + the silver crawlers + the Athena workgroup.

**Status:** migrated in **PR-012** from `terraform-lottery/Prod/{glue_crawlers.tf,
glue_crawlers_silver.tf, athena.tf}` via cross-state `terraform state rm` (legacy) +
`terraform import` (main). See `docs/runbooks/PR-012-catalog-orchestration-migration.md`.

## PR-012 decisions

- **Legacy `processed/` crawlers deleted from code** (`lottery-premios-crawler`,
  `lottery-sorteos-crawler`): they point at the `processed/` prefix the new transformer no
  longer writes. They were `state rm`'d (left unmanaged in AWS, deletable by hand whenever).
  The underlying S3 prefix `processed/` is **preserved** (not deleted).
- **`null_resource "run_glue_crawlers"` triggers deleted:** the Step Function starts the
  crawlers; apply-time triggers are not needed (they were already commented out since the
  PR-004 state reconstruction and never re-imported).
- **The Athena workgroup (`lottery-wg`) lives here:** the roadmap assigned it no module and
  the legacy folder is deleted in PR-015; the catalog module owns the query layer.

## Inputs / outputs

- Inputs: `database_name` (default `lottery_santalucia_db`), `glue_crawler_role_arn`,
  `partitioned_bucket_name`, `athena_results_bucket_name`, `environment`.
- Outputs: `db_name`, `premios_silver_crawler_name`, `sorteos_silver_crawler_name`,
  `athena_workgroup_name`.

## PR-022 decision: no gold crawler

The roadmap's PR-022 step 4 planned a `RunGoldCrawler` over `s3://<partitioned>/gold/`.
**It was deliberately skipped.** Athena CTAS `CREATE TABLE` registers each `gold_*` table
— including its partition metadata — directly in this database. Because the gold build
fully drops and recreates every table on each run (see the orchestration module's
`BuildGold` Map + the `gold-purge` Lambda), the catalog is always current the moment the
CTAS finishes. A crawler would only re-scan data CTAS already registered — pure runtime
cost with no benefit.

A crawler would earn its place only if the gold build switched from *recreate* to
`INSERT INTO` (append), where newly written partitions would need discovery. That is not
the current design; revisit if it changes.

## Log retention (PR-023) — `/aws-glue/crawlers` is ACCOUNT-WIDE

Crawlers have no per-crawler log group; every crawler in the account writes to
`/aws-glue/crawlers`. Owning it here is the only way to set its retention, so the same
`manage_shared_glue_log_groups` gate as the `etl-glue` module applies. The group already
exists in prod and is `terraform import`ed — see `docs/runbooks/PR-023-log-retention.md`.

Extra inputs: `log_retention_days` (default 30), `manage_shared_glue_log_groups`.
Extra output: `crawler_log_group_name`.

## Tables DEFINED here, not crawled (PR-044.2, PR-045.2)

Three of this database's tables have their schema declared in `main.tf` rather than inferred
by a crawler:

| Table | Since | Imported? |
|---|---|---|
| `quarantine_rejects` | PR-044.2 | no — created by Terraform |
| `silver_sorteos_sorteos` | PR-045.2 | **yes** — `terraform import`, see below |
| `silver_premios_premios` | PR-045.2 | **yes** |

**Why.** PR-045.1 established, against the live account, that the two Silver crawlers cannot
evolve a schema: `SchemaChangePolicy.UpdateBehavior = "LOG"` detects a change and writes a
log line, `CRAWL_NEW_FOLDERS_ONLY` never revisits an existing partition, and
`Partitions.AddOrUpdateBehavior = "InheritFromTable"` gives a new partition the *table's*
schema rather than its files'. Four lineage columns were being written into every new Parquet
file and none of them reached Athena.

**The crawlers were not loosened, and that is the design.** `UPDATE_IN_DATABASE` +
`CRAWL_EVERYTHING` would hand the schema of the two tables seven gold CTAS queries read to a
process that re-infers it weekly. The same three settings that hid the columns are what make
a declared schema safe — a crawler that will not alter a table cannot fight it — and
`InheritFromTable` now stamps each new partition with the declared schema. The crawlers keep
registering the week's new partition, which is the job they are still needed for.

**⚠️ The two Silver tables already existed and are IMPORTED.** A create would drop and rebuild
the table Athena reads, losing 118 registered partitions. The import commands and the
expected plan are in `docs/runbooks/PR-045.2-lineage-queryable.md` §2.

**⚠️ Column contracts.** `local.lineage_columns` (rendered into both Silver tables by a
`dynamic` block, so the two cannot drift apart) is the other half of
`loteria.common.lineage.LINEAGE_GLUE_TYPES`, and the quarantine column list is the other half
of `QUARANTINE_COLUMNS`. Tests read this file and compare — nothing else would notice them
separating, and the symptom of drift is a query error months later.

**Types are `bigint`, not `int`, wherever pandas writes an integer.** pandas writes a Python
int as int64; Athena widens INT to BIGINT and supports nothing in the other direction, so an
`int` declaration over this data cannot be read. Corrected for `quarantine_rejects` in
PR-045.2, before the table had a row.

The views over these tables (`silver_lineage`, `silver_lineage_runs`) are deliberately NOT
here — see `sql/lineage/README.md`.
