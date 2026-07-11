# Module: etl-lambda
# The extractor Lambda function (scrapes loteria.org.gt) and its deployment artifact.
# Migrated from terraform-lottery/Prod/lambdas.tf in PR-010 via cross-state
# `terraform state rm` (legacy) + `terraform import` (here) — the function is NOT
# recreated. See docs/runbooks/PR-010-lambda-migration.md.
#
# PR-010 also changes the function's environment on purpose (an in-place update, not a
# no-op): the PARTITIONED_BUCKET / SIMPLE_BUCKET values switch from bucket ARNs to bucket
# NAMES, and LOTERIA_SECRET_NAME is added. Safe today because the extractor code reads
# its config from Secrets Manager, not from these env vars; PR-017 switches the code to
# consume them.

# The deployment artifact, uploaded from a local zip. The owner keeps the local file in
# sync with the deployed object (see runbook) so `etag` / `source_code_hash` match state.
resource "aws_s3_object" "lambda_package" {
  bucket = var.lambda_code_bucket
  key    = var.lambda_zip_key
  source = var.lambda_zip_path
  etag   = filemd5(var.lambda_zip_path)
}

# Lambda: Extractor
resource "aws_lambda_function" "extractor_lambda" {
  function_name    = "lottery-extractor-${var.environment}"
  s3_bucket        = var.lambda_code_bucket
  s3_key           = aws_s3_object.lambda_package.key
  source_code_hash = filebase64sha256(var.lambda_zip_path)
  handler          = "extractor.lambda_handler.lambda_handler"
  runtime          = "python3.12"
  timeout          = 120
  memory_size      = 1024
  role             = var.lambda_exec_role_arn

  environment {
    variables = {
      # PR-010: bucket NAMES (not ARNs) + the secret name. The code reads config from
      # Secrets Manager until PR-017 teaches it to prefer these.
      PARTITIONED_BUCKET  = var.partitioned_bucket_name
      SIMPLE_BUCKET       = var.simple_bucket_name
      REGION              = var.region
      LOTERIA_SECRET_NAME = var.secret_name
    }
  }

  depends_on = [
    aws_s3_object.lambda_package
  ]

  tags = {
    Name        = "lottery-extractor-${var.environment}"
    Environment = var.environment
    Project     = "Lottery ETL"
    Owner       = "Angel Hackerman"
  }
}
