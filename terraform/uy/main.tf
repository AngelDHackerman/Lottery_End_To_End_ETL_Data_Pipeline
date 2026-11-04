# Stack: Uruguay (UY-041.1). docs/uruguay/DESIGN.md § Nube, D24–D30.
#
# A separate root with its own state (backend.tf), so `make deploy` of Santa Lucía never sees
# these resources and nothing here can change Santa Lucía's: its buckets are READ through data
# sources, never managed.
#
# Holds (UY-041.1):
#   - the Glue database lottery_uy_db and its Lake Formation registration of uy/silver (D25)
#   - the three roles: fetch Lambda, silver Lambda, GX Glue job (iam.tf)
# Holds (UY-041.2):
#   - the DynamoDB manifest table (P16, manifest.tf)
#   - the ECR repository for the silver Lambda's image (D29, ecr.tf)
#
# Left alone on purpose: the account-wide Lake Formation settings (data lake admins). Santa
# Lucía does not manage them either; it is one object per account, and declaring it here
# would overwrite the admins set in the console.

data "aws_caller_identity" "current" {}

# The data bucket Santa Lucía owns (module.storage, prevent_destroy). UY writes only under uy/.
data "aws_s3_bucket" "partitioned" {
  bucket = "lottery-partitioned-storage-${var.environment}"
}

# Where the build artifacts go: UY's under uy/ (the GX wheels zip and its script, D30).
data "aws_s3_bucket" "code" {
  bucket = "lambda-code-zip-${var.environment}"
}

locals {
  account_id = data.aws_caller_identity.current.account_id

  # D24 / P15: one top-level prefix per layer, mirroring data/uy/ on disk (uy/gold/ arrives
  # with UY-044).
  raw_prefix       = "uy/raw/"
  silver_prefix    = "uy/silver/"
  artifacts_prefix = "uy/"

  # Named here so the roles can scope their log grants before the functions exist
  # (UY-042/043 create them, with their log groups declared first: PR-023's rule).
  fetch_function_name  = "lottery-uy-fetch-${var.environment}"
  silver_function_name = "lottery-uy-silver-${var.environment}"
}

# --- Catalog (D25) ------------------------------------------------------------------------

resource "aws_glue_catalog_database" "uy" {
  name        = var.database_name
  description = "Uruguay (DNLQ) lottery data: silver and gold. Managed by terraform/uy."
}

# Register uy/silver with Lake Formation, like the main stack registers silver/. The two paths
# do not nest, so LF accepts both. No `hybrid_access_enabled`: the same registration settings
# as silver/, which are the ones known to work in this account.
resource "aws_lakeformation_resource" "silver" {
  arn                     = "${data.aws_s3_bucket.partitioned.arn}/${trimsuffix(local.silver_prefix, "/")}"
  use_service_linked_role = true
}

# No role here reads through the catalog yet: the silver Lambda writes Parquet straight to S3
# and the GX job reads it the same way (D20). Table grants land with the tables, in UY-042.
resource "aws_lakeformation_permissions" "iam_allowed_principals_compat" {
  count = var.enable_iam_allowed_principals_compat ? 1 : 0

  principal   = "IAM_ALLOWED_PRINCIPALS"
  permissions = ["CREATE_TABLE", "ALTER", "DROP", "DESCRIBE"]

  database {
    name = aws_glue_catalog_database.uy.name
  }
}
