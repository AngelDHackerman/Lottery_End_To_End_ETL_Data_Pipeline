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
  description = "The nightly state machine (UY-043.3.1), its log group, its failure alarm and its schedule (UY-043.3.2)."
  value = {
    name      = aws_sfn_state_machine.pipeline.name
    arn       = aws_sfn_state_machine.pipeline.arn
    log_group = aws_cloudwatch_log_group.pipeline.name
    alarm     = aws_cloudwatch_metric_alarm.pipeline_failed.alarm_name
    schedule  = "${aws_scheduler_schedule.nightly.name}: ${aws_scheduler_schedule.nightly.schedule_expression} ${aws_scheduler_schedule.nightly.schedule_expression_timezone}"
  }
}

output "dq_job" {
  description = "The silver gate's Glue job (UY-043.4), its artifacts and where its lines go."
  value = {
    name      = aws_glue_job.silver_dq.name
    script    = "s3://${aws_s3_object.dq_script.bucket}/${aws_s3_object.dq_script.key}"
    wheels    = "s3://${aws_s3_object.dq_zip.bucket}/${aws_s3_object.dq_zip.key}"
    log_group = "/aws-glue/jobs/output"
  }
}

output "athena" {
  description = "UY's Athena workgroup and the silver tables it reads (UY-044.1)."
  value = {
    workgroup     = aws_athena_workgroup.uy.name
    results       = aws_athena_workgroup.uy.configuration[0].result_configuration[0].output_location
    silver_tables = sort([for t in aws_glue_catalog_table.silver : t.name])
  }
}

output "gold_function" {
  description = "The gold Lambda (UY-044.3), its role (the one the bucket's delete-Deny must exempt under uy/gold/) and its log group."
  value = {
    name      = aws_lambda_function.gold.function_name
    role_arn  = aws_iam_role.gold_lambda.arn
    prefix    = "s3://${data.aws_s3_bucket.partitioned.bucket}/${local.gold_prefix}"
    log_group = aws_cloudwatch_log_group.gold.name
  }
}

output "alarms" {
  description = "The alarms on nights that do not fail (UY-045); the failure alarm is in state_machine."
  value = sort(concat(
    [for a in aws_cloudwatch_metric_alarm.nightly_count : a.alarm_name],
    [aws_cloudwatch_metric_alarm.pipeline_no_success.alarm_name],
  ))
}
