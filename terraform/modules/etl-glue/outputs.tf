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

# PR-024: the two groups by ROLE, so consumers don't have to know Glue's naming or index
# into log_group_names. Emitted from constants, NOT from the resources, so they stay
# correct when manage_shared_glue_log_groups = false — the groups exist in AWS whether or
# not Terraform owns them, and a dashboard still needs to read them.
output "output_log_group_name" {
  description = "Log group carrying the Glue job's stdout (structured JSON logs)."
  value       = local.glue_output_log_group
}

output "error_log_group_name" {
  description = "Log group carrying the Glue job's stderr and tracebacks."
  value       = local.glue_error_log_group
}
