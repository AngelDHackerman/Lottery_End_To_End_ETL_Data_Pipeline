# The silver Lambda (UY-042.4.1). DESIGN.md D17, D18, D29.
#
# A container image from the ECR repo of UY-041.2: the silver dependencies (pyarrow above all)
# do not fit a zip. The image is built and pushed by `make uy-silver-push` and named by
# var.silver_image_tag, a hash of its inputs (scripts/uy_silver_tag.py), so an unchanged tree
# plans no change. `make uy-tf-plan` passes the tag and refuses to plan if it is not in ECR yet:
# Lambda checks the image exists when it creates or updates the function.
#
# It copies uy/silver/ to /tmp, reads the manifest with one Scan, downloads the bronze it needs
# in parallel, rebuilds the years it is given with the same code as `make uy-silver`, and
# uploads what changed (sorteos.uy.lambda_silver). Invoked by hand in
# UY-042.4 (`make uy-silver-invoke`); Step Functions runs it per year in UY-043.

resource "aws_cloudwatch_log_group" "silver" {
  #checkov:skip=CKV_AWS_158:no secrets in these logs; the AWS managed key is enough
  name              = "/aws/lambda/${local.silver_function_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "silver" {
  #checkov:skip=CKV_AWS_115:the account's concurrency limit is 10 and AWS keeps all 10 unreserved
  #checkov:skip=CKV_AWS_116:invoked synchronously (by hand now, by Step Functions in UY-043); a failure returns to the caller
  #checkov:skip=CKV_AWS_117:outside the VPC on purpose (D26): it only talks to S3 and DynamoDB, and a VPC would need endpoints
  #checkov:skip=CKV_AWS_173:the environment holds resource names and no secret
  #checkov:skip=CKV_AWS_272:code signing does not apply to container images; the image is built from a hashed lock and an image pinned by digest
  #checkov:skip=CKV_AWS_50:no X-Ray anywhere in the repo; the function returns its own timings
  function_name = local.silver_function_name
  role          = aws_iam_role.silver_lambda.arn
  package_type  = "Image"
  image_uri     = "${aws_ecr_repository.silver.repository_url}:${var.silver_image_tag}"
  architectures = ["x86_64"] # the image's base and wheels are linux/amd64

  # D18: one year took 14.9 s at most locally (2011), the whole history ~281 s. The Lambda reads
  # bronze from S3 instead of a disk, which is what UY-042.4.1 measures. 15 minutes is the most
  # Lambda allows; 2 GB buys more than one vCPU for pyarrow and the PDF parsing.
  timeout     = 900
  memory_size = 2048

  # /tmp holds the bronze a run reads (owner, UY-042.4.1 1a): one year's pages plus every
  # pozos PDF is ~150 MB, all of bronze ~1.05 GB. 2 GB leaves room for several years per run.
  ephemeral_storage {
    size = 2048
  }

  environment {
    variables = {
      MANIFEST_TABLE = aws_dynamodb_table.manifest.name
      SILVER_BUCKET  = data.aws_s3_bucket.partitioned.bucket
      SILVER_PREFIX  = local.silver_prefix
      BRONZE_PREFIX  = local.raw_prefix
      # Turns on the nightly metric line (sorteos.core.metrics; alarms.tf, UY-045).
      METRICS_ENVIRONMENT = var.environment
    }
  }

  depends_on = [aws_cloudwatch_log_group.silver, aws_ecr_repository_policy.silver]
}
