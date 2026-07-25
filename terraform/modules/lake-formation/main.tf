# Module: lake-formation
# Codifies the Lake Formation setup that was previously done by hand in the console
# (see challanges_faced.md §5), so a fresh deploy needs ZERO console clicks before the
# silver crawlers can run.
#
# NEW resources (PR-013): nothing here is imported — aws_lakeformation_resource has no
# import support, and LF grants are additive. Applying over an account that already has
# the equivalent manual grants is safe; see docs/runbooks/PR-013-lake-formation.md for
# the one AlreadyExists caveat on the path registration.

# Register the silver/ prefix of the partitioned bucket with Lake Formation, using the
# AWSServiceRoleForLakeFormationDataAccess service-linked role (created on demand).
resource "aws_lakeformation_resource" "silver" {
  arn                     = "${var.partitioned_bucket_arn}/silver"
  use_service_linked_role = true
}

# Database-level DDL for the crawler role: create/alter/drop/describe tables in the db.
resource "aws_lakeformation_permissions" "crawler_database" {
  principal   = var.glue_crawler_role_arn
  permissions = ["CREATE_TABLE", "ALTER", "DROP", "DESCRIBE"]

  database {
    name = var.database_name
  }
}

# Table-level access for the crawler role on every table in the db.
#
# Do NOT write `permissions = ["ALL"]` here. Lake Formation expands "ALL" (Super)
# server-side into the six permissions below and reads them back expanded, so a config
# saying ["ALL"] never matches its own read-back — Terraform then wants to REPLACE this
# grant on every plan, forever (revoking + re-granting the crawler's access each apply).
# Enumerating the same six permissions is equivalent and reads back cleanly.
#
# No `permissions_with_grant_option`: a grant option lets the principal re-grant a
# permission to OTHER principals. A crawler only reads S3 and writes table metadata — it
# never delegates — so grant options here would be privilege with no use case.
resource "aws_lakeformation_permissions" "crawler_all_tables" {
  principal   = var.glue_crawler_role_arn
  permissions = ["ALTER", "DELETE", "DESCRIBE", "DROP", "INSERT", "SELECT"]

  table {
    database_name = var.database_name
    wildcard      = true
  }
}

# S3 data-location access on the registered silver path for the crawler role.
resource "aws_lakeformation_permissions" "crawler_silver_location" {
  principal   = var.glue_crawler_role_arn
  permissions = ["DATA_LOCATION_ACCESS"]

  data_location {
    arn = aws_lakeformation_resource.silver.arn
  }
}

# ===========================================================================
# GOLD LAYER (PR-022)
# ===========================================================================
# The gold tables live in the same LF-governed database as silver. The manual PR-021
# CTAS runs created gold_* tables owned by the console admin, so the automation roles
# have no LF rights on them until granted here. Same pattern as the crawler grants above;
# ["ALL"] is avoided for the same never-settles read-back reason (see the note above).

# Gold-purge Lambda: drop each gold table before its CTAS. DROP needs DESCRIBE alongside.
resource "aws_lakeformation_permissions" "gold_purge_tables" {
  principal   = var.gold_purge_lambda_role_arn
  permissions = ["DESCRIBE", "DROP"]

  table {
    database_name = var.database_name
    wildcard      = true
  }
}

# Step Function role: run the CTAS. Needs CREATE_TABLE on the database to register each
# fresh gold table.
resource "aws_lakeformation_permissions" "sfn_database" {
  principal   = var.sfn_execution_role_arn
  permissions = ["CREATE_TABLE", "ALTER", "DROP", "DESCRIBE"]

  database {
    name = var.database_name
  }
}

# Step Function role: read silver (SELECT/DESCRIBE) and manage the gold tables it creates.
# gold/ is NOT registered with LF (only silver/ is), so writing gold Parquet is governed
# by the SFN role's IAM s3:PutObject — no DATA_LOCATION_ACCESS grant is required here.
resource "aws_lakeformation_permissions" "sfn_all_tables" {
  principal   = var.sfn_execution_role_arn
  permissions = ["ALTER", "DELETE", "DESCRIBE", "DROP", "INSERT", "SELECT"]

  table {
    database_name = var.database_name
    wildcard      = true
  }
}

# IAMAllowedPrincipals compatibility grant. Required while the account runs LF in
# "Hybrid access mode" (the default here — "Make Lake Formation permissions effective
# immediately" unchecked), where Glue falls back to IAM-only authorization. Disable
# (var = false) only after moving the account to full LF enforcement, i.e. once every
# principal that queries the catalog has explicit LF grants.
resource "aws_lakeformation_permissions" "iam_allowed_principals_compat" {
  count = var.enable_iam_allowed_principals_compat ? 1 : 0

  principal   = "IAM_ALLOWED_PRINCIPALS"
  permissions = ["CREATE_TABLE", "ALTER", "DROP", "DESCRIBE"]

  database {
    name = var.database_name
  }
}
