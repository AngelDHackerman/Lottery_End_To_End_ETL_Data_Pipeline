# Remote state for the URUGUAY stack (terraform/uy/), UY-041.1.
#
# Same state bucket + lock table as the main stack, a DIFFERENT key, so neither stack can
# see (or destroy) the other's resources:
#   - main stack (Santa Lucía): main/terraform.tfstate
#   - this stack (Uruguay):     uy/terraform.tfstate
#
# ⚠️ Never init this stack with ../backend.hcl: that file sets key = "main/terraform.tfstate",
# and a -backend-config file overrides the key below. This stack would then plan to destroy
# every Santa Lucía resource. Use `make uy-tf-init`, which reads terraform/uy/backend.hcl (no
# key) and passes the key on the command line, last, so it always wins.
terraform {
  backend "s3" {
    key            = "uy/terraform.tfstate"
    dynamodb_table = "loteria-tf-locks"
    encrypt        = true
  }
}
