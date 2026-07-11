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
