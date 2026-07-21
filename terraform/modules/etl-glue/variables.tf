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

# --- Runtime versions (PR-020 spike: stay on Python Shell 3.9; see main.tf note) ---
variable "glue_version" {
  description = "INERT for a pythonshell job — AWS stores it but ignores it at runtime (the live job reads back \"3.0\"). Not a Spark glue_version. Kept at \"3.0\" to match imported state; the runtime is set by python_version."
  type        = string
  default     = "3.0"
}

variable "python_version" {
  description = "Python version for the pythonshell job. Only \"3.6\" (EOL 2026-03-01) and \"3.9\" are supported; \"3.9\" is the sole current runtime. Reaching 3.10+ requires migrating the job type away from pythonshell."
  type        = string
  default     = "3.9"
}
