# MOVED in PR-011 → terraform/modules/etl-glue/
#
# The Glue transform job (aws_glue_job.lottery_transform) was migrated to the etl-glue
# module via cross-state `terraform state rm` (here) + `terraform import` (into the main
# stack). The job was NOT recreated. The hard-coded script_location
# ("s3://lambda-code-zip-prod/lottery_transformer.zip") became
# "s3://${code_bucket}/${script_key}" in the module (same value in prod).
# See docs/runbooks/PR-011-glue-migration.md.
#
# This file is intentionally left as a pointer; the whole terraform-lottery/Prod/ folder
# is deleted in PR-015 once every module has migrated.
