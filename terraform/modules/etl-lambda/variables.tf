# Input variables for the "etl-lambda" module.

variable "environment" {
  description = "Deployment environment suffix used in resource names (e.g. \"prod\")."
  type        = string
}

variable "region" {
  description = "AWS region, passed to the function as the REGION env var."
  type        = string
}

# --- Deployment artifact ---
variable "lambda_code_bucket" {
  description = "Name of the bucket holding the Lambda deployment zip (from module.storage)."
  type        = string
}

variable "lambda_zip_key" {
  description = "S3 key of the Lambda deployment zip."
  type        = string
  default     = "lambda_package.zip"
}

variable "lambda_zip_path" {
  description = "Local path to the code-only Lambda zip (uploaded + hashed). Built by scripts/build_lambda_function.sh via `make build`."
  type        = string
}

# --- Dependency layer (PR-019) ---
variable "lambda_layer_zip_key" {
  description = "S3 key of the dependency layer zip."
  type        = string
  default     = "lambda_layer.zip"
}

variable "lambda_layer_zip_path" {
  description = "Local path to the dependency layer zip (uploaded + hashed). Built by scripts/build_lambda_layer.sh via `make build`."
  type        = string
}

# --- IAM (from module.iam) ---
variable "lambda_exec_role_arn" {
  description = "ARN of the extractor Lambda execution role."
  type        = string
}

# --- Runtime config passed as env vars (bucket NAMES, not ARNs) ---
variable "partitioned_bucket_name" {
  description = "Name of the partitioned (raw/silver/gold) data bucket."
  type        = string
}

variable "secret_name" {
  description = "Name of the lottery secret in Secrets Manager, passed as LOTERIA_SECRET_NAME."
  type        = string
}

# --- Observability (PR-023) ---
variable "log_retention_days" {
  description = "Retention for the extractor's CloudWatch log group. 0 = never expire."
  type        = number
  default     = 30
}

# --- scrape.do proxy profile (PR-031.1) ---
#
# On 2026-08-20 loteria.org.gt tightened Cloudflare and the previous profile (geoCode=MX,
# no render, no super) stopped working entirely: every request came back
# `502 ROTATION_FAILED / "cannot connect target url"`. Only Guatemalan residential IPs with
# headless rendering get through, and all three settings are required TOGETHER — every
# proper subset was tested against the live site and still failed.
#
# These are exposed as variables so the profile can be retuned without rebuilding the
# Lambda zip. The defaults match the code's own defaults in scraping.py; changing one here
# without changing the other leaves two sources of truth disagreeing.

variable "scrape_geo_code" {
  description = "scrape.do geoCode for the extractor. GT (Guatemala) is residential-only."
  type        = string
  default     = "GT"
}

variable "scrape_render" {
  description = "Route through scrape.do's headless browser. Required to pass Cloudflare."
  type        = bool
  default     = true
}

variable "scrape_super" {
  description = "Use residential/mobile IPs. Required for geoCode=GT and to pass Cloudflare."
  type        = bool
  default     = true
}

variable "scrape_timeout" {
  description = <<-EOT
    Per-request timeout in seconds for the scrape.do call.

    Must stay ABOVE scrape.do's own ~57 s give-up, or a proxy failure surfaces as a local
    ReadTimeout and the real 502 never reaches the logs — the bug that made the 2026-08
    outage take two weeks to diagnose. Must also leave room for two calls inside the
    Lambda's 120 s timeout.
  EOT
  type        = number
  default     = 60

  validation {
    condition     = var.scrape_timeout >= 58 && var.scrape_timeout <= 110
    error_message = "scrape_timeout must be 58-110s: above scrape.do's ~57s give-up, below the Lambda's 120s ceiling."
  }
}
