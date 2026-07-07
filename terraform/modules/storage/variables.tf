# Input variables for the "storage" module.

variable "environment" {
  description = "Deployment environment suffix baked into bucket names (e.g. \"prod\"). Must match the real deployed names for the PR-007 import to be a no-op."
  type        = string
}
