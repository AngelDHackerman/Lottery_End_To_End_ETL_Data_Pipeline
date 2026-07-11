# Outputs exposed by the "lake-formation" module.

output "silver_location_arn" {
  description = "ARN of the silver/ S3 path registered with Lake Formation."
  value       = aws_lakeformation_resource.silver.arn
}
