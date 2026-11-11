# UY-044.3 — gold: the Lambda that builds the six tables beside the published ones and swaps
# them whole (sorteos.core.gold; DESIGN.md D33; owner, UY-044.3 1a-4a).
#
# What it may do, and nothing more:
#   - run queries in UY's workgroup, reading silver through Lake Formation (SELECT on the seven
#     silver tables) and writing the CTAS output under uy/gold/;
#   - create, update and delete the tables gold_* and stg_gold_* of lottery_uy_db;
#   - delete under uy/gold/, to retire old generations. The bucket's Deny (PR-002) still refuses
#     it until the owner adds this role to its exemption, scoped to uy/gold/
#     (docs/runbooks/UY-044-gold.md): that policy is not managed by Terraform.
#
# uy/gold/ is NOT registered with Lake Formation, like Santa Lucía's gold/: the CTAS writes
# with this role's own S3 permissions, and the tables it creates are its own.

locals {
  gold_prefix        = "uy/gold/"
  gold_function_name = "lottery-uy-gold-${var.environment}"

  # The zip: the two modules, the three package __init__s and the SQL. Nothing else of
  # `sorteos` goes in, so a change to a parser never redeploys this function.
  gold_package = merge(
    {
      "sorteos/__init__.py"       = "${path.module}/../../src/sorteos/__init__.py"
      "sorteos/core/__init__.py"  = "${path.module}/../../src/sorteos/core/__init__.py"
      "sorteos/core/gold.py"      = "${path.module}/../../src/sorteos/core/gold.py"
      "sorteos/uy/__init__.py"    = "${path.module}/../../src/sorteos/uy/__init__.py"
      "sorteos/uy/lambda_gold.py" = "${path.module}/../../src/sorteos/uy/lambda_gold.py"
    },
    {
      for name in fileset("${path.module}/../../sql/uy/gold", "*.sql") :
      "sql/uy/gold/${name}" => "${path.module}/../../sql/uy/gold/${name}"
    }
  )
}

# archive_file writes fixed timestamps and sorted entries: the same files give the same zip,
# so a plan with no change in them shows no change here (PR-046).
data "archive_file" "gold" {
  type        = "zip"
  output_path = "${path.module}/../../dist/uy/uy_gold.zip"

  dynamic "source" {
    for_each = local.gold_package
    content {
      filename = source.key
      content  = file(source.value)
    }
  }
}

resource "aws_cloudwatch_log_group" "gold" {
  #checkov:skip=CKV_AWS_158:no secrets in these logs; the AWS managed key is enough
  name              = "/aws/lambda/${local.gold_function_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_iam_role" "gold_lambda" {
  name               = "lottery-uy-gold-lambda-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "gold_lambda" {
  statement {
    sid    = "QueryInUyWorkgroup"
    effect = "Allow"
    actions = [
      "athena:StartQueryExecution",
      "athena:GetQueryExecution",
      "athena:GetQueryResults",
      "athena:StopQueryExecution",
    ]
    resources = [aws_athena_workgroup.uy.arn]
  }

  # Reading: the database and every table of it (Athena plans a query through the catalog).
  statement {
    sid    = "ReadUyCatalog"
    effect = "Allow"
    actions = [
      "glue:GetDatabase",
      "glue:GetTable",
      "glue:GetTables",
      "glue:GetPartition",
      "glue:GetPartitions",
    ]
    resources = [
      "arn:aws:glue:${var.aws_region}:${local.account_id}:catalog",
      aws_glue_catalog_database.uy.arn,
      "arn:aws:glue:${var.aws_region}:${local.account_id}:table/${aws_glue_catalog_database.uy.name}/*",
    ]
  }

  # Writing: only gold tables and their staging twins. Silver's tables are Terraform's.
  statement {
    sid    = "WriteGoldTables"
    effect = "Allow"
    actions = [
      "glue:CreateTable",
      "glue:UpdateTable",
      "glue:DeleteTable",
    ]
    resources = [
      "arn:aws:glue:${var.aws_region}:${local.account_id}:catalog",
      aws_glue_catalog_database.uy.arn,
      "arn:aws:glue:${var.aws_region}:${local.account_id}:table/${aws_glue_catalog_database.uy.name}/gold_*",
      "arn:aws:glue:${var.aws_region}:${local.account_id}:table/${aws_glue_catalog_database.uy.name}/stg_gold_*",
    ]
  }

  # Silver's location is registered with Lake Formation: the bytes come through LF's vended
  # credentials, which need this action besides the LF grant below (PR-013's lesson).
  statement {
    sid       = "LakeFormationDataAccess"
    effect    = "Allow"
    actions   = ["lakeformation:GetDataAccess"]
    resources = ["*"]
  }

  statement {
    sid    = "ListGoldAndItsVersions"
    effect = "Allow"
    actions = [
      "s3:ListBucket",
      "s3:ListBucketVersions",
    ]
    resources = [data.aws_s3_bucket.partitioned.arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = [local.gold_prefix, "${local.gold_prefix}*"]
    }
  }

  statement {
    sid       = "LocateBuckets"
    effect    = "Allow"
    actions   = ["s3:GetBucketLocation"]
    resources = [data.aws_s3_bucket.partitioned.arn, data.aws_s3_bucket.athena_results.arn]
  }

  # The only prefix of the data bucket this role can write to or delete from. The versions
  # too: the bucket is versioned, and a delete without them frees nothing.
  statement {
    sid    = "WriteAndRetireGold"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:AbortMultipartUpload",
      "s3:DeleteObject",
      "s3:DeleteObjectVersion",
    ]
    resources = ["${data.aws_s3_bucket.partitioned.arn}/${local.gold_prefix}*"]
  }

  # Athena writes every query's result (the row counts too) under the workgroup's location.
  statement {
    sid       = "ListOwnQueryResults"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [data.aws_s3_bucket.athena_results.arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["uy/", "uy/*"]
    }
  }

  statement {
    sid    = "WriteOwnQueryResults"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:AbortMultipartUpload",
    ]
    resources = ["${data.aws_s3_bucket.athena_results.arn}/uy/*"]
  }

  statement {
    sid       = "WriteOwnLogs"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["arn:aws:logs:${var.aws_region}:${local.account_id}:log-group:/aws/lambda/${local.gold_function_name}:*"]
  }
}

resource "aws_iam_role_policy" "gold_lambda" {
  name   = "lottery-uy-gold-lambda-${var.environment}"
  role   = aws_iam_role.gold_lambda.id
  policy = data.aws_iam_policy_document.gold_lambda.json
}

# --- Lake Formation -----------------------------------------------------------------------
#
# Explicit permissions, never ALL (it never settles in a plan), per table and on the database
# (PR-013, PR-042.3). On the tables this role creates it needs no grant: it is their creator.

resource "aws_lakeformation_permissions" "gold_reads_silver" {
  for_each = aws_glue_catalog_table.silver

  principal   = aws_iam_role.gold_lambda.arn
  permissions = ["SELECT", "DESCRIBE"]

  table {
    database_name = each.value.database_name
    name          = each.value.name
  }
}

# ALTER and DROP are here because Lake Formation reports them: this was applied with
# CREATE_TABLE and DESCRIBE alone, and after the first build the grant read back with all four
# (2026-11-11), so the next plan wanted to replace it, forever. Declaring what is there settles
# it (master's PR-013a lesson: an LF grant is what LF says it is). They give the role nothing
# it can use: its IAM policy has no glue:UpdateDatabase or DeleteDatabase, and limits table
# changes to gold_* and stg_gold_*.
resource "aws_lakeformation_permissions" "gold_creates_tables" {
  principal   = aws_iam_role.gold_lambda.arn
  permissions = ["ALTER", "CREATE_TABLE", "DESCRIBE", "DROP"]

  database {
    name = aws_glue_catalog_database.uy.name
  }
}

# --- The function -------------------------------------------------------------------------

resource "aws_lambda_function" "gold" {
  #checkov:skip=CKV_AWS_115:the account's concurrency limit is 10 and AWS keeps all 10 unreserved; one execution a night calls it
  #checkov:skip=CKV_AWS_116:invoked synchronously by Step Functions, so a failure is the state's failure; there is nothing to dead-letter
  #checkov:skip=CKV_AWS_117:outside the VPC like the other UY Lambdas (D26); it only calls AWS APIs
  #checkov:skip=CKV_AWS_173:the environment holds four resource names and no secret
  #checkov:skip=CKV_AWS_272:code signing is not used anywhere in the repo
  #checkov:skip=CKV_AWS_50:no X-Ray anywhere in the repo; the function's report is its trace
  function_name    = local.gold_function_name
  role             = aws_iam_role.gold_lambda.arn
  filename         = data.archive_file.gold.output_path
  source_code_hash = data.archive_file.gold.output_base64sha256
  handler          = "sorteos.uy.lambda_gold.handler"
  runtime          = "python3.12"
  architectures    = ["x86_64"]

  # Six CTAS of a few seconds each, started together, then one count and six swaps. The
  # builder gives Athena 150 s before it stops the queries itself; 180 s also keeps the state
  # machine's worst case under its hour (pipeline.tf).
  timeout     = var.gold_timeout_seconds
  memory_size = 256

  environment {
    variables = {
      GOLD_DATABASE  = aws_glue_catalog_database.uy.name
      GOLD_WORKGROUP = aws_athena_workgroup.uy.name
      GOLD_BUCKET    = data.aws_s3_bucket.partitioned.bucket
      GOLD_PREFIX    = local.gold_prefix
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.gold,
    aws_iam_role_policy.gold_lambda,
    aws_lakeformation_permissions.gold_reads_silver,
    aws_lakeformation_permissions.gold_creates_tables,
  ]
}

# --- Who can read lottery_uy_db in Athena (UY-044.3.1) -------------------------------------
#
# The gold tables are created by the Lambda's role, and the account's Lake Formation settings
# give a new table to its creator alone (CreateTableDefaultPermissions is empty). So the first
# build left six tables nobody else could query, the data lake administrators included:
# Athena answered "Relation contains no accessible columns". Being an administrator lets a
# principal GRANT, it does not let it SELECT.
#
# A table wildcard, because the gold tables are not Terraform's to name: it covers the six of
# today and any the SQL folder adds, and silver too. Read-only, and explicit (never ALL).
#
# The readers: whoever applies this stack, when that is an IAM user (the owner; an assumed
# role's session ARN is not a principal Lake Formation accepts), plus var.catalog_reader_arns.
locals {
  deployer_arn = data.aws_caller_identity.current.arn
  catalog_readers = toset(concat(
    var.catalog_reader_arns,
    can(regex(":user/", local.deployer_arn)) ? [local.deployer_arn] : [],
  ))
}

resource "aws_lakeformation_permissions" "catalog_readers" {
  for_each = local.catalog_readers

  principal   = each.value
  permissions = ["SELECT", "DESCRIBE"]

  table {
    database_name = aws_glue_catalog_database.uy.name
    wildcard      = true
  }
}
