output "database_name" {
  description = "The UY Glue/Lake Formation database (D25)."
  value       = aws_glue_catalog_database.uy.name
}

output "silver_location" {
  description = "The Lake Formation registered location for UY silver."
  value       = aws_lakeformation_resource.silver.arn
}

output "prefixes" {
  description = "Where each UY layer lives in the data bucket (D24, P15)."
  value = {
    bucket = data.aws_s3_bucket.partitioned.bucket
    raw    = local.raw_prefix
    silver = local.silver_prefix
  }
}

output "fetch_lambda_role_arn" {
  description = "Role for the fetch Lambda (UY-042/043)."
  value       = aws_iam_role.fetch_lambda.arn
}

output "silver_lambda_role_arn" {
  description = "Role for the silver Lambda (UY-042/043)."
  value       = aws_iam_role.silver_lambda.arn
}

output "dq_glue_role_arn" {
  description = "Role for the GX Glue 5.0 job (D30)."
  value       = aws_iam_role.dq_glue.arn
}

output "function_names" {
  description = "The names the roles' log grants are scoped to; UY-042/043 must use them."
  value = {
    fetch  = local.fetch_function_name
    silver = local.silver_function_name
  }
}

output "manifest_table" {
  description = "The DynamoDB manifest (D28, P16) and its sparse index of open keys."
  value = {
    name       = aws_dynamodb_table.manifest.name
    arn        = aws_dynamodb_table.manifest.arn
    open_index = "open-keys"
  }
}

output "silver_ecr_repository_url" {
  description = "Where UY-042 pushes the silver Lambda image (D29)."
  value       = aws_ecr_repository.silver.repository_url
}

output "fetch_function" {
  description = "The fetch Lambda (UY-042.3) and its log group."
  value = {
    name      = aws_lambda_function.fetch.function_name
    arn       = aws_lambda_function.fetch.arn
    log_group = aws_cloudwatch_log_group.fetch.name
  }
}

output "silver_function" {
  description = "The silver Lambda (UY-042.4.1), the image it runs and its log group."
  value = {
    name      = aws_lambda_function.silver.function_name
    image_uri = aws_lambda_function.silver.image_uri
    log_group = aws_cloudwatch_log_group.silver.name
  }
}

output "pipeline" {
  description = "The nightly state machine (UY-043.3.1), its log group and its failure alarm."
  value = {
    name      = aws_sfn_state_machine.pipeline.name
    arn       = aws_sfn_state_machine.pipeline.arn
    log_group = aws_cloudwatch_log_group.pipeline.name
    alarm     = aws_cloudwatch_metric_alarm.pipeline_failed.alarm_name
  }
}
