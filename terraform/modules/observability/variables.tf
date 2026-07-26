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

# --- Dashboard (PR-024) ---
# The dashboard reads metrics only, so these are names/ARNs for identifying series —
# nothing here creates a dependency on the observed resources' internals.

variable "aws_region" {
  description = "Region the dashboard's widgets query."
  type        = string
}

variable "state_machine_arn" {
  description = "ARN of the pipeline state machine (AWS/States StateMachineArn dimension)."
  type        = string
}

variable "extractor_lambda_name" {
  description = "Name of the extractor Lambda (AWS/Lambda FunctionName dimension)."
  type        = string
}

variable "gold_purge_lambda_name" {
  description = "Name of the gold-purge Lambda (AWS/Lambda FunctionName dimension)."
  type        = string
}

variable "athena_workgroup_name" {
  description = "Athena workgroup the gold CTAS runs in (AWS/Athena WorkGroup dimension)."
  type        = string
}

variable "glue_output_log_group_name" {
  description = "Log group holding the Glue job's stdout (structured JSON). Source for the transform log widget — Glue publishes no per-job CloudWatch metrics for Python Shell jobs, so logs are the only Glue-side signal. From module.etl_glue (PR-023)."
  type        = string
}

variable "glue_error_log_group_name" {
  description = "Log group holding the Glue job's stderr/tracebacks. Source for the error log widget. From module.etl_glue (PR-023)."
  type        = string
}
