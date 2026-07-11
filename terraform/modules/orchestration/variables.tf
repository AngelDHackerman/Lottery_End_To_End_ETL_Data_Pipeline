# Input variables for the "orchestration" module.

variable "environment" {
  description = "Deployment environment suffix used in resource names (e.g. \"prod\")."
  type        = string
}

# --- IAM (from module.iam) ---
variable "sfn_execution_role_arn" {
  description = "ARN of the Step Functions execution role."
  type        = string
}

variable "eventbridge_to_sfn_role_arn" {
  description = "ARN of the EventBridge -> Step Functions role."
  type        = string
}

# --- Pipeline pieces the Step Function drives (from etl-lambda / etl-glue / catalog) ---
variable "extractor_lambda_arn" {
  description = "ARN of the extractor Lambda function."
  type        = string
}

variable "glue_job_name" {
  description = "Name of the transform Glue job."
  type        = string
}

variable "premios_crawler_name" {
  description = "Name of the silver premios crawler."
  type        = string
}

variable "sorteos_crawler_name" {
  description = "Name of the silver sorteos crawler."
  type        = string
}
