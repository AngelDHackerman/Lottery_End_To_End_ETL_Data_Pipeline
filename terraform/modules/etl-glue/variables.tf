# Input variables for the "etl-glue" module.

variable "environment" {
  description = "Deployment environment suffix used in resource names (e.g. \"prod\")."
  type        = string
}

# --- Script artifact (replaces the old hard-coded s3:// path) ---
variable "code_bucket" {
  description = "Name of the bucket holding the transformer script zip (from module.storage)."
  type        = string
}

variable "script_key" {
  description = "S3 key of the transformer script zip."
  type        = string
  default     = "lottery_transformer.zip"
}

# --- IAM (from module.iam) ---
variable "glue_job_role_arn" {
  description = "ARN of the Glue transform job role."
  type        = string
}

# --- Secrets Manager ---
variable "secret_name" {
  description = "Name of the lottery secret in Secrets Manager, passed to the job as the LOTERIA_SECRET_NAME argument (which the code reads as an env var)."
  type        = string
}

# --- Job arguments ---
variable "partitioned_bucket_name" {
  description = "Name of the partitioned (raw/silver/gold) data bucket."
  type        = string
}

variable "simple_bucket_name" {
  description = "Name of the simple / EDA dataset bucket."
  type        = string
}

# --- Runtime versions (TODO PR-020: upgrade spike to 4.0 / 3.10) ---
variable "glue_version" {
  description = "Glue runtime version."
  type        = string
  default     = "3.0"
}

variable "python_version" {
  description = "Python version for the pythonshell job."
  type        = string
  default     = "3.9"
}
