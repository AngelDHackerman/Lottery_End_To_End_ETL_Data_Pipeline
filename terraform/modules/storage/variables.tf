# Input variables for the "storage" module.

variable "environment" {
  description = "Deployment environment suffix baked into bucket names (e.g. \"prod\"). Must match the real deployed names for the PR-007 import to be a no-op."
  type        = string
}

variable "code_noncurrent_version_days" {
  description = "Days an overwritten artifact in the code bucket is kept before it expires (PR-054). This is the rollback window: a previous lambda_package.zip or Glue zip can be restored for this long. The live version of each key never expires."
  type        = number
  default     = 90

  validation {
    condition     = var.code_noncurrent_version_days >= 7
    error_message = "Keep at least 7 days of previous artifact versions: the pipeline runs weekly, so a shorter window can expire the last good build before a bad one is noticed."
  }
}
