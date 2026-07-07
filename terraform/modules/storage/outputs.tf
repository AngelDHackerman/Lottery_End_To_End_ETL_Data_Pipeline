# Outputs exposed by the "storage" module.
# Consumed by later modules (etl-lambda, etl-glue, iam, orchestration) as they migrate.

output "partitioned_bucket_name" {
  description = "Name of the partitioned (raw/silver/gold) data bucket."
  value       = aws_s3_bucket.lottery_partitioned.bucket
}

output "partitioned_bucket_arn" {
  description = "ARN of the partitioned data bucket."
  value       = aws_s3_bucket.lottery_partitioned.arn
}

output "simple_bucket_name" {
  description = "Name of the simple / EDA dataset bucket."
  value       = aws_s3_bucket.lottery_simple.bucket
}

output "simple_bucket_arn" {
  description = "ARN of the simple dataset bucket."
  value       = aws_s3_bucket.lottery_simple.arn
}

output "athena_results_bucket_name" {
  description = "Name of the Athena query-results bucket."
  value       = aws_s3_bucket.athena_results.bucket
}

output "lambda_code_bucket_name" {
  description = "Name of the Lambda deployment-artifact bucket."
  value       = aws_s3_bucket.lambda_code_zip.bucket
}
