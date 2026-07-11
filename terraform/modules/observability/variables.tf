# Input variables for the "observability" module.

variable "environment" {
  description = "Deployment environment suffix used in resource names (e.g. \"prod\")."
  type        = string
}

variable "alert_email" {
  description = "Email address subscribed to the alerts topic. Empty = no subscription. The recipient must confirm the subscription email AWS sends (PR-028 documents this in tfvars)."
  type        = string
  default     = ""
}
