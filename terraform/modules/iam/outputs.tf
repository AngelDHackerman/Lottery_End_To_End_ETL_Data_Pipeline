# Outputs exposed by the "iam" module.
# Consumed by etl-lambda (PR-010), etl-glue (PR-011), catalog + orchestration (PR-012),
# and sagemaker (PR-015) as they migrate.

output "lambda_exec_role_arn" {
  description = "ARN of the extractor Lambda execution role."
  value       = aws_iam_role.lambda_exec.arn
}

output "glue_job_role_arn" {
  description = "ARN of the Glue transform job role."
  value       = aws_iam_role.glue_job_role.arn
}

output "glue_crawler_role_arn" {
  description = "ARN of the Glue crawler role."
  value       = aws_iam_role.glue_crawler_role.arn
}

output "sfn_execution_role_arn" {
  description = "ARN of the Step Functions execution role."
  value       = aws_iam_role.sfn_execution_role.arn
}

output "eventbridge_to_sfn_role_arn" {
  description = "ARN of the EventBridge -> Step Functions role."
  value       = aws_iam_role.eventbridge_to_sfn_role.arn
}

output "sagemaker_execution_role_arn" {
  description = "ARN of the SageMaker Studio execution role."
  value       = aws_iam_role.sagemaker_execution_role.arn
}

output "gold_purge_lambda_role_arn" {
  description = "ARN of the gold-purge Lambda execution role (PR-022)."
  value       = aws_iam_role.gold_purge_lambda.arn
}
