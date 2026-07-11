# MOVED in PR-012 → terraform/modules/orchestration/
#
# The state machine (aws_sfn_state_machine.pipeline_state_machine) was migrated to the
# orchestration module via cross-state `terraform state rm` (here) + `terraform import`
# (into the main stack). It was NOT recreated; its definition now references the catalog
# module's crawler outputs (same names). See
# docs/runbooks/PR-012-catalog-orchestration-migration.md.
#
# This file is intentionally left as a pointer; the whole terraform-lottery/Prod/ folder
# is deleted in PR-015 once every module has migrated.
