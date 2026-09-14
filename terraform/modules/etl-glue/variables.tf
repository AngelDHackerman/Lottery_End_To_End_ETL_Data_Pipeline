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

# --- PR-033: the Silver data-quality gate job -------------------------------------------
# A second, separate Glue job. It shares this module because it is a Glue job, but it shares
# almost nothing else with the transform job above: different job type, different runtime,
# different role, read-only. Hence its own variable block rather than reusing the ones above.

variable "enable_silver_dq" {
  description = "Create the Silver DQ job and its log group. Off leaves the rest of the module untouched, so the stack can be applied before scripts/build_dq_package.sh has produced and uploaded the artifacts."
  type        = bool
  default     = true
}

variable "dq_job_role_arn" {
  description = "ARN of the READ-ONLY Glue role for the Silver DQ job (from module.iam). Deliberately not glue_job_role_arn: the transform role can write and delete across both data buckets, and a validator that can modify what it validates is not a gate."
  type        = string
}

variable "dq_script_key" {
  description = "S3 key of the DQ job's entry-point script. A Spark job's script_location must be a plain .py file, not a zip — built by scripts/build_dq_package.sh."
  type        = string
  default     = "loteria_silver_dq.py"
}

variable "dq_lib_key" {
  description = "S3 key of the zipped `loteria` package, passed to the DQ job as --extra-py-files. Must be uploaded together with dq_script_key: the script imports loteria.dq from it, so a stale zip fails at import inside the job, not at deploy time."
  type        = string
  default     = "loteria_dq_lib.zip"
}

variable "dq_glue_version" {
  description = "Glue version for the DQ job. REAL here, unlike the pythonshell glue_version above: for glueetl this selects the runtime. 5.0 = Python 3.11, which is the whole reason this job is a Spark job — great-expectations 1.x needs >= 3.10 and Python Shell caps at 3.9."
  type        = string
  default     = "5.0"
}

variable "great_expectations_version" {
  description = "GX version pip-installed into the DQ job via --additional-python-modules. MUST match the pin in requirements/dq.txt — that file is the version the suites were verified against, and a drift here means the gate runs code the tests never saw."
  type        = string
  default     = "1.20.0"
}

variable "silver_prefix" {
  description = "Silver layer prefix the DQ job validates. Matches SILVER_PREFIX_DEFAULT in loteria/dq/runner.py and the transformer's write path."
  type        = string
  default     = "silver/"
}

variable "dq_timeout_minutes" {
  description = "Hard stop for the DQ job. The observed run is seconds (~117k rows across ~222 files, dominated by the S3 reads), so this is a runaway guard, not a budget — a hung validation must not bill for the Glue default of 2880 minutes."
  type        = number
  default     = 30
}
