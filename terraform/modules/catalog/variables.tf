# Input variables for the "catalog" module.

variable "environment" {
  description = "Deployment environment suffix used in resource names (e.g. \"prod\")."
  type        = string
}

variable "database_name" {
  description = "Name of the Glue catalog database."
  type        = string
  default     = "lottery_santalucia_db"
}

# --- IAM (from module.iam) ---
variable "glue_crawler_role_arn" {
  description = "ARN of the Glue crawler role."
  type        = string
}

# --- Buckets (from module.storage) ---
variable "partitioned_bucket_name" {
  description = "Name of the partitioned (raw/silver/gold) data bucket the crawlers scan."
  type        = string
}

variable "athena_results_bucket_name" {
  description = "Name of the Athena query-results bucket for the workgroup."
  type        = string
}
