# Remote state backend for the MAIN Terraform stack (terraform/).
#
# This stack shares the SAME state bucket + lock table as the legacy stack
# (terraform-lottery/Prod) created by the bootstrap in PR-003, but uses a
# DIFFERENT key so their states never collide:
#   - main stack (this one): main/terraform.tfstate
#   - legacy stack:          legacy/terraform.tfstate
#
# `key`, `dynamodb_table`, and `encrypt` are baked in here so they can't be set
# wrong. `bucket` and `region` are environment-specific and are supplied at init
# time from backend.hcl (copy backend.hcl.example -> backend.hcl):
#
#   cd terraform
#   terraform init -backend-config=backend.hcl
#
# backend.hcl is gitignored; backend.hcl.example is the committed template.
terraform {
  backend "s3" {
    key            = "main/terraform.tfstate"
    dynamodb_table = "loteria-tf-locks"
    encrypt        = true
  }
}
