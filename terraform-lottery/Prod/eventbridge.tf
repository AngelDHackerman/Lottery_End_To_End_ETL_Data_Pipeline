# MOVED in PR-012 → terraform/modules/orchestration/
#
# The weekly trigger (aws_cloudwatch_event_rule.weekly_etl_trigger, Mon 18:00 UTC) and
# its target (aws_cloudwatch_event_target.trigger_step_function) were migrated to the
# orchestration module via cross-state `terraform state rm` (here) + `terraform import`
# (into the main stack). This is the rule that was KEPT; the duplicate Saturday rule
# (cloudwatch_event_rule.tf / cloudwatch_event_target.tf) is destroyed.
# See docs/runbooks/PR-012-catalog-orchestration-migration.md.
#
# This file is intentionally left as a pointer; the whole terraform-lottery/Prod/ folder
# is deleted in PR-015 once every module has migrated.
