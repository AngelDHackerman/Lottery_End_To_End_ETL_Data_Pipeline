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

# --- Observability: log retention (PR-023) ---

variable "log_retention_days" {
  description = "Retention for every CloudWatch log group this stack owns. 0 = never expire. Crank it up for a long-lived prod; 30 keeps the free-tier bill flat."
  type        = number
  default     = 30

  validation {
    # CloudWatch only accepts this fixed set; anything else fails at apply time with an
    # unhelpful InvalidParameterException, so catch it at plan time instead.
    condition = contains(
      [0, 1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1096, 1827, 2192, 2557, 2922, 3288, 3653],
      var.log_retention_days
    )
    error_message = "log_retention_days must be one of the values CloudWatch accepts (0, 1, 3, 5, 7, 14, 30, 60, 90, 120, 150, 180, 365, 400, 545, 731, 1096, 1827, 2192, 2557, 2922, 3288, 3653)."
  }
}

variable "manage_shared_glue_log_groups" {
  description = "Let this stack own the ACCOUNT-WIDE Glue log groups (/aws-glue/python-jobs/{output,error}, /aws-glue/crawlers). Glue writes Python Shell + crawler logs to these shared groups rather than per-job ones, so this is the only way to set their retention — but every Glue job/crawler in the account shares them. Set false if the account hosts Glue workloads this repo does not own."
  type        = bool
  default     = true
}

variable "sfn_log_level" {
  description = "Step Functions execution logging level: OFF, ERROR, FATAL or ALL. ALL is the default because the pipeline runs once a week (~15 state transitions), so the log volume is negligible next to the debugging value. OFF skips the log group and the logging_configuration entirely."
  type        = string
  default     = "ALL"

  validation {
    condition     = contains(["OFF", "ERROR", "FATAL", "ALL"], var.sfn_log_level)
    error_message = "sfn_log_level must be one of OFF, ERROR, FATAL, ALL."
  }
}

variable "sfn_include_execution_data" {
  description = "Include state input/output payloads in the Step Functions logs. On for this pipeline: the payloads are gold SQL keys and CTAS statements, not sensitive data, and they are what makes a failed run readable."
  type        = bool
  default     = true
}

# --- lake-formation module (PR-013) ---
variable "enable_iam_allowed_principals_compat" {
  description = "Keep the IAMAllowedPrincipals LF database grant (Hybrid access mode compatibility). Disable only after moving to full LF enforcement."
  type        = bool
  default     = true
}

# --- etl-lambda module (PR-010; artifacts split in PR-019) ---
variable "lambda_zip_path" {
  description = "Local path to the code-only Lambda zip (relative to terraform/). Produced by `make build` — no longer hand-synced from S3."
  type        = string
  default     = "lambda_package.zip"
}

variable "lambda_layer_zip_path" {
  description = "Local path to the dependency layer zip (relative to terraform/). Produced by `make build`."
  type        = string
  default     = "lambda_layer.zip"
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

# --- Custom metrics (PR-026) ---
variable "metrics_namespace" {
  description = "CloudWatch namespace for the pipeline's own metrics (scraper HTTP status; PR-027's S3 object counts would join it). Threaded to both the iam module (scopes PutMetricData via the cloudwatch:namespace condition) and the observability module (the dashboard SEARCH). MUST equal loteria.common.metrics.NAMESPACE — a mismatch denies every publish, silently."
  type        = string
  default     = "Loteria/Pipeline"
}
