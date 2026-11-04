# The fetch Lambda (UY-042.3). DESIGN.md D26, D29.
#
# In UY-042.3 it only runs the probe of D26 (`make uy-fetch-probe`): it asks the site again for
# the newest draw of each source and compares the bytes with the manifest, writing nothing.
# No schedule here: EventBridge Scheduler and Step Functions arrive in UY-043, with the real
# fetch, the day the local incremental is switched off (G4).
#
# The zip (dist/uy/uy_fetch.zip, `make uy-fetch-build`) is uploaded straight from disk: at
# ~2 MB it is far under the 50 MB direct-upload limit, so there is no S3 object to keep in
# step. It must exist before `terraform plan`, which hashes it; `make uy-tf-plan` builds it.

# Declared before the function (PR-023): otherwise the first invocation creates the group
# itself, with no retention. 365 days of a few KB per run cost nothing.
resource "aws_cloudwatch_log_group" "fetch" {
  #checkov:skip=CKV_AWS_158:no secrets in these logs; the AWS managed key is enough
  name              = "/aws/lambda/${local.fetch_function_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "fetch" {
  #checkov:skip=CKV_AWS_115:the account's concurrency limit is 10 and AWS keeps all 10 unreserved; overlapping runs are stopped by the manifest's conditional writes (UY-042.2)
  #checkov:skip=CKV_AWS_116:invoked synchronously (by hand now, by Step Functions in UY-043), so a failure returns to the caller; there is nothing to dead-letter
  #checkov:skip=CKV_AWS_117:outside the VPC on purpose (D26), like Santa Lucía's Lambdas: a VPC would need a NAT gateway to reach the site
  #checkov:skip=CKV_AWS_173:the environment holds two resource names and no secret
  #checkov:skip=CKV_AWS_272:code signing is not used anywhere in the repo; the zip is built from a hashed lock
  #checkov:skip=CKV_AWS_50:no X-Ray anywhere in the repo; the function's own log line is the trace
  function_name    = local.fetch_function_name
  role             = aws_iam_role.fetch_lambda.arn
  filename         = var.fetch_zip_path
  source_code_hash = filebase64sha256(var.fetch_zip_path)
  handler          = "sorteos.uy.lambda_fetch.handler"
  runtime          = "python3.12"
  architectures    = ["x86_64"] # the lock's compiled wheels (pyyaml, charset_normalizer)

  # The probe is 8 requests at 1 per second, with at most 2 short retries each. 5 minutes
  # leaves room for a slow site without letting a blocked one hang for long.
  timeout     = 300
  memory_size = 256

  environment {
    variables = {
      MANIFEST_TABLE = aws_dynamodb_table.manifest.name
      BRONZE_BUCKET  = data.aws_s3_bucket.partitioned.bucket
      BRONZE_PREFIX  = local.raw_prefix
    }
  }

  depends_on = [aws_cloudwatch_log_group.fetch]
}
