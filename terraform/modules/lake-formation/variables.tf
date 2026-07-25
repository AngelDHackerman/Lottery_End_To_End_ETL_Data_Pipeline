# Input variables for the "lake-formation" module.

variable "partitioned_bucket_arn" {
  description = "ARN of the partitioned data bucket; its silver/ prefix gets registered with Lake Formation."
  type        = string
}

variable "glue_crawler_role_arn" {
  description = "ARN of the Glue crawler role receiving the LF grants."
  type        = string
}

variable "database_name" {
  description = "Name of the Glue catalog database the grants apply to (from module.catalog)."
  type        = string
}

variable "enable_iam_allowed_principals_compat" {
  description = "Keep the IAMAllowedPrincipals database grant for LF Hybrid access mode compatibility. Disable only after moving the account to full LF enforcement."
  type        = bool
  default     = true
}

# --- Gold layer roles (PR-022) ---
# Hybrid mode does NOT exempt these from LF: tables created under an LF-governed database
# (like the gold_* tables from the manual PR-021 runs) require explicit LF grants for a
# principal to DROP/CREATE them, regardless of IAM. Without these, the gold-purge Lambda
# fails DeleteTable ("Insufficient Lake Formation permission(s): Required Drop") and the
# SFN CTAS fails CreateTable.
variable "sfn_execution_role_arn" {
  description = "ARN of the Step Functions execution role — runs the gold CTAS (needs LF CREATE_TABLE on the db + SELECT on silver)."
  type        = string
}

variable "gold_purge_lambda_role_arn" {
  description = "ARN of the gold-purge Lambda role — drops each gold table before its CTAS (needs LF DROP)."
  type        = string
}
