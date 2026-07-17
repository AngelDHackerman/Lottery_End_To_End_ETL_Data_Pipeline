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

# PR-019 splits the single fat artifact in two: `loteria/` ships in the function zip and
# its third-party deps (requests, beautifulsoup4) ship in a layer. Build both with
# `make build` BEFORE applying — see docs/runbooks/PR-019-lambda-layer.md.

# The function's code-only artifact, uploaded from the locally built zip.
resource "aws_s3_object" "lambda_package" {
  bucket = var.lambda_code_bucket
  key    = var.lambda_zip_key
  source = var.lambda_zip_path
  etag   = filemd5(var.lambda_zip_path)
}

# The dependency layer's artifact. Separate S3 object so a code change no longer
# re-uploads the deps, and vice versa.
resource "aws_s3_object" "lambda_layer" {
  bucket = var.lambda_code_bucket
  key    = var.lambda_layer_zip_key
  source = var.lambda_layer_zip_path
  etag   = filemd5(var.lambda_layer_zip_path)
}

# Layer versions are immutable: a new source_code_hash publishes version N+1 rather than
# mutating N. `create_before_destroy` makes Terraform publish the new version and repoint
# the function BEFORE deleting the old one — the default destroy-then-create order would
# briefly delete the version the live function is still using.
resource "aws_lambda_layer_version" "loteria_deps" {
  layer_name = "loteria-deps-${var.environment}"
  s3_bucket  = var.lambda_code_bucket
  s3_key     = aws_s3_object.lambda_layer.key
  # Publish from the object we just uploaded, not whatever S3 held before this apply.
  source_code_hash = filebase64sha256(var.lambda_layer_zip_path)

  compatible_runtimes = ["python3.12"]
  # charset_normalizer is the only non-pure-python dep, and pip resolves its wheel for
  # the *build host*. Its mypyc .so is therefore x86_64-linux-specific; declaring the
  # arch keeps this layer off arm64 functions, where that .so is dead weight and the
  # package silently falls back to its slower pure-python path.
  compatible_architectures = ["x86_64"]

  description = "requests + beautifulsoup4 for the extractor (pinned in requirements/extractor.txt)"

  lifecycle {
    create_before_destroy = true
  }
}

# Lambda: Extractor
resource "aws_lambda_function" "extractor_lambda" {
  function_name    = "lottery-extractor-${var.environment}"
  s3_bucket        = var.lambda_code_bucket
  s3_key           = aws_s3_object.lambda_package.key
  source_code_hash = filebase64sha256(var.lambda_zip_path)

  # PR-016: the zip carries the `loteria` package at its root (was a bare `extractor/`),
  # so the handler path gains the package prefix. Rebuild the zip (`make build`) BEFORE
  # applying.
  handler     = "loteria.extractor.lambda_handler.lambda_handler"
  runtime     = "python3.12"
  timeout     = 120
  memory_size = 1024
  role        = var.lambda_exec_role_arn

  # PR-019: requests/beautifulsoup4 now arrive via the layer, mounted at /opt.
  layers = [aws_lambda_layer_version.loteria_deps.arn]

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
