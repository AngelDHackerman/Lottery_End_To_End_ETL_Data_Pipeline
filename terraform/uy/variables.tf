variable "aws_region" {
  description = "AWS region for all resources."
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment suffix used in resource names (e.g. \"prod\")."
  type        = string
  default     = "prod"
}

variable "database_name" {
  description = "Glue/Lake Formation database for Uruguay (D25)."
  type        = string
  default     = "lottery_uy_db"
}

# Same switch, same reason as the main stack's lake-formation module: while the account runs
# Lake Formation in hybrid access mode, Glue falls back to IAM for principals without LF
# grants, and that fallback needs this grant on every database, the new one included.
variable "enable_iam_allowed_principals_compat" {
  description = "Grant IAM_ALLOWED_PRINCIPALS on the UY database (needed in LF hybrid access mode)."
  type        = bool
  default     = true
}
