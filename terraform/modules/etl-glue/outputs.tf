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
