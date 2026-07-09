# MOVED in PR-009 → terraform/modules/iam/
#
# All IAM roles, customer-managed policies, and attachments that used to live here
# (lambda_exec, glue_job_role, glue_crawler_role, sagemaker_execution_role + their
# policies/attachments, and the athena_results_access policy) were migrated to the iam
# module via cross-state `terraform state rm` (here) + `terraform import` (into the main
# stack). No role/policy was recreated. See docs/runbooks/PR-009-iam-migration.md.
#
# The two personal IAM-user attachments (santa-lucia-dev, angel-adming) are now gated
# behind var.personal_iam_users in the module (default empty). Other legacy files that
# referenced these roles (glue_job.tf, glue_crawlers*.tf, state_machine.tf,
# eventbridge.tf, cloudwatch_event_target.tf) now use literal role ARNs (same values)
# until PR-012 wires them to the iam module outputs.
#
# This file is intentionally left as a pointer; the whole terraform-lottery/Prod/ folder
# is deleted in PR-015 once every module has migrated.
