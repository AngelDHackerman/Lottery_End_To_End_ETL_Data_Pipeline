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

# --- Gold layer (PR-022) ---
variable "partitioned_bucket_name" {
  description = "Name of the partitioned bucket. Gold SQL is uploaded to its sql/gold/ prefix; the purge Lambda reads from there and empties gold/<name>/ before each CTAS."
  type        = string
}

variable "database_name" {
  description = "Glue catalog database the CTAS statements target (from module.catalog.db_name)."
  type        = string
}

variable "athena_workgroup_name" {
  description = "Athena workgroup the gold CTAS runs in (from module.catalog.athena_workgroup_name)."
  type        = string
}

variable "gold_purge_lambda_role_arn" {
  description = "Execution role ARN for the gold-purge Lambda (from module.iam)."
  type        = string
}

# --- Observability (PR-023) ---
variable "log_retention_days" {
  description = "Retention for the gold-purge Lambda + Step Functions log groups. 0 = never expire."
  type        = number
  default     = 30
}

variable "sfn_log_level" {
  description = "Step Functions execution logging level: OFF, ERROR, FATAL or ALL. OFF skips both the log group and the logging_configuration."
  type        = string
  default     = "ALL"

  validation {
    condition     = contains(["OFF", "ERROR", "FATAL", "ALL"], var.sfn_log_level)
    error_message = "sfn_log_level must be one of OFF, ERROR, FATAL, ALL."
  }
}

variable "sfn_include_execution_data" {
  description = "Include state input/output payloads in the Step Functions logs."
  type        = bool
  default     = true
}

# --- Silver-crawler completion polling (PR-026.1) ---
# The state machine waits for both silver crawlers to finish before building gold. There is
# no `.sync` integration for startCrawler, so "waiting" means polling GetCrawler in a loop.

variable "crawler_poll_interval_seconds" {
  description = "Seconds to wait between GetCrawler polls while a silver crawler runs. 30 keeps the extra latency under a poll interval without spamming the Glue API (a crawl takes minutes, not seconds)."
  type        = number
  default     = 30

  validation {
    condition     = var.crawler_poll_interval_seconds >= 5 && var.crawler_poll_interval_seconds <= 300
    error_message = "crawler_poll_interval_seconds must be between 5 and 300."
  }
}

variable "crawler_poll_max_attempts" {
  description = "Polls before the execution fails with CrawlerPollTimeout. Guards against a hung crawler looping forever. Default 30 x 30 s = 15 minutes; the observed worst case is 4m26s wall clock, of which only the first ~46 s is catalog work — the rest is the crawler's own teardown before it reports READY."
  type        = number
  default     = 30

  validation {
    condition     = var.crawler_poll_max_attempts >= 1 && var.crawler_poll_max_attempts <= 200
    error_message = "crawler_poll_max_attempts must be between 1 and 200."
  }
}
