# Outputs exposed by the "etl-glue" module.
# Consumed by the iam module (narrowed glue:StartJobRun grant) and the
# orchestration module (PR-012, Step Function definition).

output "glue_job_name" {
  description = "Name of the Glue transform job."
  value       = aws_glue_job.lottery_transform.name
}

output "glue_job_arn" {
  description = "ARN of the Glue transform job."
  value       = aws_glue_job.lottery_transform.arn
}

# PR-023: names of the (account-shared) Glue log groups this module retains. Empty when
# manage_shared_glue_log_groups = false.
output "log_group_names" {
  description = "Names of the Glue Python Shell log groups managed here."
  value       = [for lg in aws_cloudwatch_log_group.python_shell : lg.name]
}
