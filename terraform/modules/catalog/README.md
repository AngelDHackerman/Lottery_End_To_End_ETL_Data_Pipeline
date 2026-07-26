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
