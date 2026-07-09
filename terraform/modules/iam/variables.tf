# Input variables for the "iam" module.

variable "environment" {
  description = "Deployment environment suffix used in resource names (e.g. \"prod\")."
  type        = string
}

variable "aws_region" {
  description = "AWS region — used to build service ARNs (lambda/glue/states)."
  type        = string
}

# --- Secret (narrowed secretsmanager grant) ---
variable "secret_name" {
  description = "Name of the lottery secret in Secrets Manager. Its ARN is resolved via a data source and used to scope the lambda/glue secretsmanager grants."
  type        = string
}

# --- Bucket references (wired from module.storage outputs) ---
variable "partitioned_bucket_name" {
  description = "Name of the partitioned (raw/silver/gold) data bucket."
  type        = string
}

variable "partitioned_bucket_arn" {
  description = "ARN of the partitioned data bucket."
  type        = string
}

variable "simple_bucket_name" {
  description = "Name of the simple / EDA dataset bucket."
  type        = string
}

variable "simple_bucket_arn" {
  description = "ARN of the simple dataset bucket."
  type        = string
}

variable "athena_results_bucket_name" {
  description = "Name of the Athena query-results bucket."
  type        = string
}

variable "lambda_code_bucket_name" {
  description = "Name of the Lambda/Glue deployment-artifact bucket."
  type        = string
}

# --- Names of resources the Step Function drives (for the narrowed glue/lambda grants).
#     Defaults match the deployed prod names; PR-010/011/012 will swap these for module
#     outputs once etl-lambda/etl-glue/catalog/orchestration have migrated. ---
variable "extractor_lambda_name" {
  description = "Name of the extractor Lambda the Step Function invokes."
  type        = string
  default     = "lottery-extractor-prod"
}

variable "glue_job_name" {
  description = "Name of the transform Glue job the Step Function starts."
  type        = string
  default     = "lottery-transform-prod"
}

variable "glue_crawler_premios_name" {
  description = "Name of the silver premios crawler the Step Function starts."
  type        = string
  default     = "lottery-premios-silver-crawler"
}

variable "glue_crawler_sorteos_name" {
  description = "Name of the silver sorteos crawler the Step Function starts."
  type        = string
  default     = "lottery-sorteos-silver-crawler"
}

# --- Personal IAM-user grants (opt-in) ---
variable "personal_iam_users" {
  description = "IAM user names to grant the Athena-results policy. Empty => none created (fresh-cloner default). The owner sets their own users in a gitignored tfvars."
  type        = list(string)
  default     = []
}
