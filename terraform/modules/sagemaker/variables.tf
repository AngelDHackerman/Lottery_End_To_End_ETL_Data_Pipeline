# Input variables for the "sagemaker" module.

variable "environment" {
  description = "Deployment environment suffix used in resource names (e.g. \"prod\")."
  type        = string
}

# --- Network (from module.network) ---
variable "vpc_id" {
  description = "ID of the VPC the Studio domain attaches to."
  type        = string
}

variable "subnet_ids" {
  description = "Private subnet IDs for the domain (VpcOnly access mode)."
  type        = list(string)
}

variable "security_group_id" {
  description = "Security group for Studio apps."
  type        = string
}

# --- IAM (from module.iam) ---
variable "sagemaker_execution_role_arn" {
  description = "ARN of the SageMaker Studio execution role."
  type        = string
}
