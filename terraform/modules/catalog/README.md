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

## Later

- **PR-022** adds the gold crawler (`s3://<partitioned>/gold/`).
