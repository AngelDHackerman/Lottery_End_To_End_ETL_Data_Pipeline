# MOVED / DELETED in PR-012 → terraform/modules/catalog/
#
# - aws_glue_catalog_database.lottery_db was migrated to the catalog module via
#   cross-state `terraform state rm` (here) + `terraform import` (into the main stack).
# - The legacy `processed/` crawlers (aws_glue_crawler.premios_crawler,
#   aws_glue_crawler.sorteos_crawler) were DELETED FROM CODE: they point at the
#   `processed/` prefix the new transformer no longer writes. They were `state rm`'d
#   (kept in AWS, unmanaged — delete by hand whenever). The S3 prefix `processed/`
#   itself is preserved.
# - The commented-out null_resource apply-time triggers are gone for good — the Step
#   Function starts the crawlers.
# See docs/runbooks/PR-012-catalog-orchestration-migration.md.
#
# This file is intentionally left as a pointer; the whole terraform-lottery/Prod/ folder
# is deleted in PR-015 once every module has migrated.
