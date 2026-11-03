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
