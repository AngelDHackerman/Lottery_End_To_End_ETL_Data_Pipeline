# MOVED in PR-012 → terraform/modules/catalog/
#
# The silver crawlers (aws_glue_crawler.premios_silver_crawler,
# aws_glue_crawler.sorteos_silver_crawler) were migrated to the catalog module via
# cross-state `terraform state rm` (here) + `terraform import` (into the main stack).
# Neither was recreated. See docs/runbooks/PR-012-catalog-orchestration-migration.md.
#
# This file is intentionally left as a pointer; the whole terraform-lottery/Prod/ folder
# is deleted in PR-015 once every module has migrated.
