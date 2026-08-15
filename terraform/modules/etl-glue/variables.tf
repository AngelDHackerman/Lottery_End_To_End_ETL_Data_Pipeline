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

# --- Observability (PR-023) ---
variable "log_retention_days" {
  description = "Retention for the Glue Python Shell log groups. 0 = never expire."
  type        = number
  default     = 30
}

variable "manage_shared_glue_log_groups" {
  description = "Own the ACCOUNT-WIDE /aws-glue/python-jobs/{output,error} groups. Glue has no per-job group for pythonshell, so this is the only way to set their retention; set false if other, non-repo Glue jobs share the account."
  type        = bool
  default     = true
}

# --- PR-033: Silver data-quality job ---------------------------------------------------
variable "enable_silver_dq" {
  description = "Create the Silver DQ Glue job. Gated so the stack can be applied before the job artifacts have been uploaded to the code bucket — Glue accepts a script_location that does not exist yet, but a run would fail, so a fresh cloner should turn this on only after `make build`."
  type        = bool
  default     = true
}

variable "glue_dq_job_role_arn" {
  description = "ARN of the Silver DQ job's role. Separate from the transform job's role: DQ only reads Silver, so it gets no write and no Secrets Manager access."
  type        = string
  default     = ""
}

variable "dq_script_key" {
  description = "S3 key of the DQ job script (a plain .py, not a zipapp — glueetl runs the script directly)."
  type        = string
  default     = "loteria_silver_dq.py"
}

variable "dq_lib_key" {
  description = "S3 key of the zipped loteria package passed to the DQ job as --extra-py-files."
  type        = string
  default     = "loteria_dq_lib.zip"
}

variable "dq_glue_version" {
  description = "Glue version for the DQ job. Load-bearing (unlike glue_version above, which is inert for pythonshell): \"5.0\" is what selects Python 3.11, the minimum great-expectations 1.x accepts."
  type        = string
  default     = "5.0"
}

variable "dq_python_modules" {
  description = "Value of --additional-python-modules for the DQ job. Installed from PyPI at run time; keep in sync with requirements/dq.txt."
  type        = string
  default     = "great-expectations==1.20.0"
}

variable "dq_timeout_minutes" {
  description = "Timeout for the DQ job. Short on purpose: the Step Function waits on it synchronously, so a hung run stalls the whole pipeline."
  type        = number
  default     = 20
}
