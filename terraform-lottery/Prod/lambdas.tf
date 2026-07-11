# MOVED in PR-010 → terraform/modules/etl-lambda/
#
# The extractor Lambda (aws_lambda_function.extractor_lambda) and its deployment
# artifact (aws_s3_object.lambda_package) were migrated to the etl-lambda module via
# cross-state `terraform state rm` (here) + `terraform import` (into the main stack).
# The function was NOT recreated. See docs/runbooks/PR-010-lambda-migration.md.
#
# This file is intentionally left as a pointer; the whole terraform-lottery/Prod/ folder
# is deleted in PR-015 once every module has migrated.
