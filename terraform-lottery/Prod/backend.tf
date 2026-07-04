# Remote state backend for the LEGACY stack (terraform-lottery/Prod).
#
# `bucket` and `region` are intentionally omitted here — they come from the
# bootstrap outputs and are supplied at init time via a partial backend config.
# Do NOT reuse terraform/backend.hcl verbatim: that file pins key=main/terraform.tfstate,
# which would collide with this stack. Pass only bucket + region at init:
#
#   terraform init -migrate-state \
#     -backend-config="bucket=loteria-tf-state-<AWS_ACCOUNT_ID>" \
#     -backend-config="region=us-east-1"
#
# The main stack (terraform/) and this legacy stack share the SAME state bucket
# and lock table but use different keys:
#   - main stack:   main/terraform.tfstate
#   - legacy stack: legacy/terraform.tfstate   <-- this stack
#
# See docs/runbooks/PR-004-state-migration.md for the full migration procedure.
terraform {
  backend "s3" {
    key            = "legacy/terraform.tfstate"
    dynamodb_table = "loteria-tf-locks"
    encrypt        = true
  }
}
