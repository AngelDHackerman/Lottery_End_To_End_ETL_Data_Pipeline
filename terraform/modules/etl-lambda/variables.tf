# Input variables for the "etl-lambda" module.

variable "environment" {
  description = "Deployment environment suffix used in resource names (e.g. \"prod\")."
  type        = string
}

variable "region" {
  description = "AWS region, passed to the function as the REGION env var."
  type        = string
}

# --- Deployment artifact ---
variable "lambda_code_bucket" {
  description = "Name of the bucket holding the Lambda deployment zip (from module.storage)."
  type        = string
}

variable "lambda_zip_key" {
  description = "S3 key of the Lambda deployment zip."
  type        = string
  default     = "lambda_package.zip"
}

variable "lambda_zip_path" {
  description = "Local path to the Lambda deployment zip (uploaded + hashed). Keep it in sync with the deployed artifact — see the PR-010 runbook."
  type        = string
}

# --- IAM (from module.iam) ---
variable "lambda_exec_role_arn" {
  description = "ARN of the extractor Lambda execution role."
  type        = string
}

# --- Runtime config passed as env vars (bucket NAMES, not ARNs) ---
variable "partitioned_bucket_name" {
  description = "Name of the partitioned (raw/silver/gold) data bucket."
  type        = string
}

variable "simple_bucket_name" {
  description = "Name of the simple / EDA dataset bucket."
  type        = string
}

variable "secret_name" {
  description = "Name of the lottery secret in Secrets Manager, passed as LOTERIA_SECRET_NAME."
  type        = string
}
