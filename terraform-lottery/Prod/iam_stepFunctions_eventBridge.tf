# MOVED in PR-009 → terraform/modules/iam/
#
# The Step Functions + EventBridge IAM (sfn_execution_role, eventbridge_to_sfn_role and
# their policies/attachments) was migrated to the iam module via cross-state
# `terraform state rm` (here) + `terraform import` (into the main stack). No role/policy
# was recreated. See docs/runbooks/PR-009-iam-migration.md.
#
# PR-009 absorbs this IAM early (ahead of PR-012's orchestration move) because the iam
# module must output sfn_execution_role_arn / eventbridge_to_sfn_role_arn. The Step
# Function glue:* grants were narrowed to the specific job + silver crawler ARNs, and the
# eventbridge->sfn grant to the state-machine ARN, in the module. PR-012 moves the
# orchestration RESOURCES (state machine, event rules) and consumes these role ARNs.
#
# This file is intentionally left as a pointer; the whole terraform-lottery/Prod/ folder
# is deleted in PR-015 once every module has migrated.
