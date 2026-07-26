# Input variables for the "orchestration" module.

variable "environment" {
  description = "Deployment environment suffix used in resource names (e.g. \"prod\")."
  type        = string
}

# --- IAM (from module.iam) ---
variable "sfn_execution_role_arn" {
  description = "ARN of the Step Functions execution role."
  type        = string
}

variable "eventbridge_to_sfn_role_arn" {
  description = "ARN of the EventBridge -> Step Functions role."
  type        = string
}

# --- Pipeline pieces the Step Function drives (from etl-lambda / etl-glue / catalog) ---
variable "extractor_lambda_arn" {
  description = "ARN of the extractor Lambda function."
  type        = string
}

variable "glue_job_name" {
  description = "Name of the transform Glue job."
  type        = string
}

variable "premios_crawler_name" {
  description = "Name of the silver premios crawler."
  type        = string
}

variable "sorteos_crawler_name" {
  description = "Name of the silver sorteos crawler."
  type        = string
}

# --- Gold layer (PR-022) ---
variable "partitioned_bucket_name" {
  description = "Name of the partitioned bucket. Gold SQL is uploaded to its sql/gold/ prefix; the purge Lambda reads from there and empties gold/<name>/ before each CTAS."
  type        = string
}

variable "database_name" {
  description = "Glue catalog database the CTAS statements target (from module.catalog.db_name)."
  type        = string
}

variable "athena_workgroup_name" {
  description = "Athena workgroup the gold CTAS runs in (from module.catalog.athena_workgroup_name)."
  type        = string
}

variable "gold_purge_lambda_role_arn" {
  description = "Execution role ARN for the gold-purge Lambda (from module.iam)."
  type        = string
}

# --- Observability (PR-023) ---
variable "log_retention_days" {
  description = "Retention for the gold-purge Lambda + Step Functions log groups. 0 = never expire."
  type        = number
  default     = 30
}

variable "sfn_log_level" {
  description = "Step Functions execution logging level: OFF, ERROR, FATAL or ALL. OFF skips both the log group and the logging_configuration."
  type        = string
  default     = "ALL"

  validation {
    condition     = contains(["OFF", "ERROR", "FATAL", "ALL"], var.sfn_log_level)
    error_message = "sfn_log_level must be one of OFF, ERROR, FATAL, ALL."
  }
}

variable "sfn_include_execution_data" {
  description = "Include state input/output payloads in the Step Functions logs."
  type        = bool
  default     = true
}
