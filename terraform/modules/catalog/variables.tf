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

# --- Observability (PR-023) ---
variable "log_retention_days" {
  description = "Retention for the Glue crawler log group. 0 = never expire."
  type        = number
  default     = 30
}

variable "manage_shared_glue_log_groups" {
  description = "Own the ACCOUNT-WIDE /aws-glue/crawlers group. Crawlers have no per-crawler group, so this is the only way to set its retention; set false if other, non-repo crawlers share the account."
  type        = bool
  default     = true
}
