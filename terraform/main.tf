# Root caller for the main Terraform stack.
#
# PR-006 SKELETON: every module below is a placeholder and its call is intentionally
# COMMENTED OUT — there is no wiring yet, so `terraform plan` is a clean no-op. Each
# subsequent PR (noted per block) uncomments its module, moves the resources in via
# `terraform state mv`, and threads the inputs/outputs through. Uncomment top-to-bottom
# in roughly dependency order: storage -> network -> iam -> etl-* -> catalog ->
# orchestration -> lake-formation -> observability -> sagemaker.

# --- PR-007: storage (imported data buckets + athena results + lambda code) ---
# module "storage" {
#   source      = "./modules/storage"
#   environment = var.environment
# }

# --- PR-008: network (VPC, subnets, endpoints, SGs; NAT gated by enable_internet) ---
# module "network" {
#   source          = "./modules/network"
#   environment     = var.environment
#   enable_internet = var.enable_internet
# }

# --- PR-009: iam (roles + policies; personal user attachments gated by a var) ---
# module "iam" {
#   source      = "./modules/iam"
#   environment = var.environment
#   # secret_arn, bucket ARNs from module.storage, etc. wired in PR-009.
# }

# --- PR-010: etl-lambda (extractor function) ---
# module "etl_lambda" {
#   source      = "./modules/etl-lambda"
#   environment = var.environment
#   # lambda_exec_role_arn, bucket names, secret_name wired in PR-010.
# }

# --- PR-011: etl-glue (transform job; script_location parameterized) ---
# module "etl_glue" {
#   source      = "./modules/etl-glue"
#   environment = var.environment
#   # code_bucket, script_key, glue_job_role_arn wired in PR-011.
# }

# --- PR-012: catalog (Glue DB + silver/gold crawlers) ---
# module "catalog" {
#   source      = "./modules/catalog"
#   environment = var.environment
# }

# --- PR-012: orchestration (Step Functions + single weekly EventBridge trigger) ---
# module "orchestration" {
#   source      = "./modules/orchestration"
#   environment = var.environment
#   # references catalog crawler names + etl module outputs, wired in PR-012.
# }

# --- PR-013: lake-formation (permissions so crawlers need no console clicks) ---
# module "lake_formation" {
#   source      = "./modules/lake-formation"
#   environment = var.environment
# }

# --- PR-014: observability (SNS alerts; dashboards/alarms added PR-024..PR-028) ---
# module "observability" {
#   source      = "./modules/observability"
#   environment = var.environment
#   alert_email = var.alert_email
# }

# --- PR-015: sagemaker (optional; gated so a fresh cloner gets nothing) ---
# module "sagemaker" {
#   source      = "./modules/sagemaker"
#   count       = var.enable_sagemaker ? 1 : 0
#   environment = var.environment
# }
