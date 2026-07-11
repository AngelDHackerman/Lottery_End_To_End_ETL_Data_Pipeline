# Outputs exposed by the "sagemaker" module.

output "domain_id" {
  description = "ID of the SageMaker Studio domain."
  value       = aws_sagemaker_domain.lottery_domain.id
}

output "domain_arn" {
  description = "ARN of the SageMaker Studio domain."
  value       = aws_sagemaker_domain.lottery_domain.arn
}
