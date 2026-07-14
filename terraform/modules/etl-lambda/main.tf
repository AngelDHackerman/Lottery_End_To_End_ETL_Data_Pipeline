# Module: etl-lambda
# The extractor Lambda function (scrapes loteria.org.gt) and its deployment artifact.
# Migrated from terraform-lottery/Prod/lambdas.tf in PR-010 via cross-state
# `terraform state rm` (legacy) + `terraform import` (here) — the function is NOT
# recreated. See docs/runbooks/PR-010-lambda-migration.md.
#
# PR-010 also changes the function's environment on purpose (an in-place update, not a
# no-op): the PARTITIONED_BUCKET / SIMPLE_BUCKET values switch from bucket ARNs to bucket
# NAMES, and LOTERIA_SECRET_NAME is added. As of PR-017 the extractor code consumes
# LOTERIA_SECRET_NAME (via loteria.common.aws_secrets.get_secrets()) to locate the
# Secrets Manager secret; the region comes from AWS_REGION, which the Lambda runtime
# sets automatically.

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

  # PR-016: the zip now carries the `loteria` package at its root (was a bare
  # `extractor/`), so the handler path gains the package prefix. Rebuild + upload the
  # zip (scripts/build_lambda_package.sh) BEFORE applying — see the PR-016 runbook.
  handler     = "loteria.extractor.lambda_handler.lambda_handler"
  runtime     = "python3.12"
  timeout     = 120
  memory_size = 1024
  role        = var.lambda_exec_role_arn

  environment {
    variables = {
      # PR-010: bucket NAMES (not ARNs) + the secret name (LOTERIA_SECRET_NAME, which
      # the code reads as of PR-017). REGION is retained for reference; get_secrets()
      # reads the region from AWS_REGION, which the Lambda runtime sets automatically.
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
