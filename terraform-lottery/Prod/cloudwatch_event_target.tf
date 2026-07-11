# DELETED in PR-012 (target of the duplicate weekly trigger).
#
# aws_cloudwatch_event_target.trigger_state_machine pointed the duplicate Saturday rule
# (cloudwatch_event_rule.tf) at the state machine. Destroyed together with its rule via
# `terraform apply` on this legacy stack.
# See docs/runbooks/PR-012-catalog-orchestration-migration.md, Step 3.
#
# This file is intentionally left as a pointer; the whole terraform-lottery/Prod/ folder
# is deleted in PR-015 once every module has migrated.
