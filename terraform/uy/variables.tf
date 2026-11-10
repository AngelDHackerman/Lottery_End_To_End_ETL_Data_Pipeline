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

variable "ecr_images_to_keep" {
  description = "How many images of the silver Lambda the ECR lifecycle policy keeps (UY-041.2)."
  type        = number
  default     = 5
}

variable "fetch_zip_path" {
  description = "The fetch Lambda's zip, built by `make uy-fetch-build` (UY-042.3)."
  type        = string
  default     = "../../dist/uy/uy_fetch.zip"
}

variable "log_retention_days" {
  description = "Retention of the UY Lambdas' log groups."
  type        = number
  default     = 365
}

# No default on purpose: `make uy-tf-plan` passes the tag of the image built from this tree.
variable "silver_image_tag" {
  description = "Tag of the silver Lambda image in ECR: scripts/uy_silver_tag.py (UY-042.4.1)."
  type        = string

  validation {
    condition     = can(regex("^s-[0-9a-f]{16}$", var.silver_image_tag))
    error_message = "silver_image_tag must be the content tag from scripts/uy_silver_tag.py (s-<16 hex>), never a moving tag like latest."
  }
}

variable "dq_zip_path" {
  description = "The DQ job's zip of wheels, built by `make uy-dq-build` (UY-026.2, UY-043.4)."
  type        = string
  default     = "../../dist/uy/uy_dq.gluewheels.zip"
}

# With fetch (900 s) and silver (900 s, twice, 60 s apart) this has to stay under the state
# machine's hour: 10 minutes leaves 4 to spare.
variable "dq_timeout_minutes" {
  description = "Timeout of the silver DQ Glue job, in minutes (UY-043.4)."
  type        = number
  default     = 10

  validation {
    condition     = var.dq_timeout_minutes >= 2 && var.dq_timeout_minutes <= 10
    error_message = "dq_timeout_minutes must be 2..10: above 10 the worst case no longer fits the state machine's one-hour timeout."
  }
}
