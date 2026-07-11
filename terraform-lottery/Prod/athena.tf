# MOVED in PR-012 → terraform/modules/catalog/
#
# The Athena workgroup (aws_athena_workgroup.lottery_wg) was migrated to the catalog
# module via cross-state `terraform state rm` (here) + `terraform import` (into the main
# stack). It was NOT recreated. See
# docs/runbooks/PR-012-catalog-orchestration-migration.md.
#
# This file is intentionally left as a pointer; the whole terraform-lottery/Prod/ folder
# is deleted in PR-015 once every module has migrated.
