# Root input variables for the main stack.
#
# Kept intentionally small in the PR-006 skeleton — only the foundational values
# the provider/backend need. Each module adds its own inputs as it is migrated
# (PR-007..PR-015); the root will thread the relevant ones through then.

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

# Subnet AZs for the network module (PR-008). Defaults match the deployed prod
# subnets; changing them would try to REPLACE the subnets, so keep them pinned.
variable "aws_availability_zone_a" {
  description = "AZ for the first private subnet and the public subnet."
  type        = string
  default     = "us-east-1a"
}

variable "aws_availability_zone_b" {
  description = "AZ for the second private subnet."
  type        = string
  default     = "us-east-1b"
}

# --- Opt-in toggles (wired up in the PRs noted; declared early so the root plan
#     is stable as modules land). ---

variable "enable_internet" {
  description = "Create the NAT/IGW egress path in the network module. TODO PR-008."
  type        = bool
  default     = false
}

variable "enable_sagemaker" {
  description = "Create the optional SageMaker module. TODO PR-015."
  type        = bool
  default     = false
}

variable "alert_email" {
  description = "Email for the SNS alerts subscription. Empty = no subscription. TODO PR-014/PR-028."
  type        = string
  default     = ""
}

# --- etl-lambda module (PR-010) ---
variable "lambda_zip_path" {
  description = "Local path to the Lambda deployment zip (relative to terraform/). Pull the deployed artifact here so hashes match state — see docs/runbooks/PR-010-lambda-migration.md. Replaced by built artifacts in PR-019."
  type        = string
  default     = "lambda_package.zip"
}

# --- iam module (PR-009) ---
variable "lottery_secret_name" {
  description = "Name of the lottery secret in Secrets Manager. Its ARN scopes the lambda/glue secretsmanager grants."
  type        = string
  default     = "lottery_secret_prod_2"
}

variable "personal_iam_users" {
  description = "IAM user names granted the Athena-results policy. Empty = none (fresh-cloner default). The owner lists their own users in a gitignored tfvars."
  type        = list(string)
  default     = []
}
