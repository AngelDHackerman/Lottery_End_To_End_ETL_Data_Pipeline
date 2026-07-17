# Outputs exposed by the "etl-lambda" module.
# Consumed by the iam module (narrowed lambda:InvokeFunction grant) and the
# orchestration module (PR-012, Step Function definition).

output "extractor_lambda_arn" {
  description = "ARN of the extractor Lambda function."
  value       = aws_lambda_function.extractor_lambda.arn
}

output "extractor_lambda_name" {
  description = "Name of the extractor Lambda function."
  value       = aws_lambda_function.extractor_lambda.function_name
}

# PR-019: versioned ARN, so it changes whenever requirements/extractor.txt does. Handy
# for confirming which layer version a run actually loaded.
output "deps_layer_arn" {
  description = "ARN (including version) of the extractor's dependency layer."
  value       = aws_lambda_layer_version.loteria_deps.arn
}
