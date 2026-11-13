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

# All of UY silver is under 5 MB, so 100 MB is 20 times a full scan of every table: room to
# grow for decades, and a runaway query (a cross join, the wrong database) stops early.
# Athena's minimum is 10 MB.
variable "athena_scan_limit_bytes" {
  description = "Per-query scan limit of the UY Athena workgroup (UY-044.1)."
  type        = number
  default     = 104857600

  validation {
    condition     = var.athena_scan_limit_bytes >= 10485760
    error_message = "athena_scan_limit_bytes must be at least 10485760 (10 MB), Athena's minimum."
  }
}

# fetch 900 + silver 900 + 60 + 900 + the DQ job 600 = 3,360 s; with 180 the worst case is
# 3,540 s, still under the state machine's hour.
variable "gold_timeout_seconds" {
  description = "Timeout of the gold Lambda, in seconds (UY-044.3)."
  type        = number
  default     = 180

  validation {
    condition     = var.gold_timeout_seconds >= 160 && var.gold_timeout_seconds <= 180
    error_message = "gold_timeout_seconds must be 160..180: the builder waits 150 s for Athena, and above 180 the worst case no longer fits the state machine's one-hour timeout."
  }
}

variable "catalog_reader_arns" {
  description = "IAM users or roles that may query every table of lottery_uy_db in Athena, besides the IAM user that applies the stack (UY-044.3.1). They still need their own IAM permissions for Athena and lakeformation:GetDataAccess."
  type        = list(string)
  default     = []
}

variable "no_success_alarm_days" {
  description = "Days without a successful execution before the dead-man alarm fires (UY-045; owner, 3a). At least 2: one daily bucket can be empty on a normal night. At most 7: CloudWatch evaluates no more than 7 days."
  type        = number
  default     = 2

  validation {
    condition     = var.no_success_alarm_days >= 2 && var.no_success_alarm_days <= 7 && floor(var.no_success_alarm_days) == var.no_success_alarm_days
    error_message = "no_success_alarm_days must be a whole number from 2 to 7."
  }
}
