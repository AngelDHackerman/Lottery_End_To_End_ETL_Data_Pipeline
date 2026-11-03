# The three UY roles (UY-041.1). Each one can touch only its own layer under uy/:
#
#   role                 uy/raw/        uy/silver/     logs
#   fetch Lambda         read + write   -              its function's group
#   silver Lambda        read           read + write   its function's group
#   GX Glue job          -              read           /aws-glue/* (Glue picks the group)
#
# No role here has s3:DeleteObject. The bucket's out-of-band Deny (PR-002) would refuse it
# anyway, and the one writer that deletes on disk (core/silver.py removing a partition that
# disappeared) is an open item for UY-042, where the silver Lambda's S3 path is designed.
#
# DynamoDB (manifest) and ECR (silver image) grants come with those resources in UY-041.2.

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "glue_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["glue.amazonaws.com"]
    }
  }
}

# --- fetch Lambda: the polite client, the classifier and the manifest (D29) ---------------

resource "aws_iam_role" "fetch_lambda" {
  name               = "lottery-uy-fetch-lambda-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "fetch_lambda" {
  statement {
    sid       = "ReadWriteBronze"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${data.aws_s3_bucket.partitioned.arn}/${local.raw_prefix}*"]
  }

  # ListBucket is a bucket-level action, so it is scoped with s3:prefix instead of the ARN.
  # Without it, a GetObject on a key that does not exist answers 403 instead of 404.
  statement {
    sid       = "ListBronze"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [data.aws_s3_bucket.partitioned.arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = [local.raw_prefix, "${local.raw_prefix}*"]
    }
  }

  # No logs:CreateLogGroup: the group is declared in Terraform before the function exists
  # (PR-023), so a missing group fails loudly instead of being created with no retention.
  statement {
    sid       = "WriteOwnLogs"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["arn:aws:logs:${var.aws_region}:${local.account_id}:log-group:/aws/lambda/${local.fetch_function_name}:*"]
  }
}

resource "aws_iam_role_policy" "fetch_lambda" {
  name   = "lottery-uy-fetch-lambda-${var.environment}"
  role   = aws_iam_role.fetch_lambda.id
  policy = data.aws_iam_policy_document.fetch_lambda.json
}

# --- silver Lambda: parsers, silver writer and draw_gaps (D29) -----------------------------

resource "aws_iam_role" "silver_lambda" {
  name               = "lottery-uy-silver-lambda-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

data "aws_iam_policy_document" "silver_lambda" {
  statement {
    sid       = "ReadBronze"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${data.aws_s3_bucket.partitioned.arn}/${local.raw_prefix}*"]
  }

  statement {
    sid       = "ReadWriteSilver"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:PutObject"]
    resources = ["${data.aws_s3_bucket.partitioned.arn}/${local.silver_prefix}*"]
  }

  statement {
    sid       = "ListBronzeAndSilver"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [data.aws_s3_bucket.partitioned.arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values = [
        local.raw_prefix, "${local.raw_prefix}*",
        local.silver_prefix, "${local.silver_prefix}*",
      ]
    }
  }

  statement {
    sid       = "WriteOwnLogs"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["arn:aws:logs:${var.aws_region}:${local.account_id}:log-group:/aws/lambda/${local.silver_function_name}:*"]
  }
}

resource "aws_iam_role_policy" "silver_lambda" {
  name   = "lottery-uy-silver-lambda-${var.environment}"
  role   = aws_iam_role.silver_lambda.id
  policy = data.aws_iam_policy_document.silver_lambda.json
}

# --- GX Glue job (D20, D30) ----------------------------------------------------------------
#
# Read-only by construction, like Santa Lucía's glue-silver-dq-role (PR-033): the thing that
# says "silver is fine" must not be able to change silver.

resource "aws_iam_role" "dq_glue" {
  name               = "lottery-uy-dq-glue-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.glue_assume.json
}

data "aws_iam_policy_document" "dq_glue" {
  statement {
    sid       = "ReadSilver"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${data.aws_s3_bucket.partitioned.arn}/${local.silver_prefix}*"]
  }

  statement {
    sid       = "ListSilver"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = [data.aws_s3_bucket.partitioned.arn]
    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = [local.silver_prefix, "${local.silver_prefix}*"]
    }
  }

  # The job script and the zip of wheels from `make uy-dq-build` (UY-026.2).
  statement {
    sid       = "ReadJobArtifacts"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${data.aws_s3_bucket.code.arn}/${local.artifacts_prefix}*"]
  }

  # Same as Santa Lucía's DQ role: a Spark job writes to the account-wide /aws-glue/jobs/*
  # groups and to its continuous-log group, and Glue picks which by job type.
  statement {
    sid    = "WriteGlueLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
      "logs:AssociateKmsKey",
    ]
    resources = [
      "arn:aws:logs:${var.aws_region}:${local.account_id}:log-group:/aws-glue/*",
      "arn:aws:logs:${var.aws_region}:${local.account_id}:log-group:/aws-glue/*:log-stream:*",
    ]
  }
}

resource "aws_iam_role_policy" "dq_glue" {
  name   = "lottery-uy-dq-glue-${var.environment}"
  role   = aws_iam_role.dq_glue.id
  policy = data.aws_iam_policy_document.dq_glue.json
}
