# Root caller for the main Terraform stack.
#
# PR-006 SKELETON: every module below is a placeholder and its call is intentionally
# COMMENTED OUT — there is no wiring yet, so `terraform plan` is a clean no-op. Each
# subsequent PR (noted per block) uncomments its module, moves the resources in via
# `terraform state mv`, and threads the inputs/outputs through. Uncomment top-to-bottom
# in roughly dependency order: storage -> network -> iam -> etl-* -> catalog ->
# orchestration -> lake-formation -> observability -> sagemaker.

# --- PR-007: storage (imported data buckets + athena results + lambda code) ---
module "storage" {
  source      = "./modules/storage"
  environment = var.environment
}

# --- PR-008: network (VPC, subnets, endpoints, SGs; NAT gated by enable_internet) ---
module "network" {
  source                  = "./modules/network"
  environment             = var.environment
  aws_region              = var.aws_region
  aws_availability_zone_a = var.aws_availability_zone_a
  aws_availability_zone_b = var.aws_availability_zone_b
  enable_internet         = var.enable_internet
}

# --- PR-009: iam (roles + policies; personal user attachments gated by a var) ---
module "iam" {
  source      = "./modules/iam"
  environment = var.environment
  aws_region  = var.aws_region
  secret_name = var.lottery_secret_name

  # Bucket references from the storage module.
  partitioned_bucket_name    = module.storage.partitioned_bucket_name
  partitioned_bucket_arn     = module.storage.partitioned_bucket_arn
  simple_bucket_name         = module.storage.simple_bucket_name
  simple_bucket_arn          = module.storage.simple_bucket_arn
  athena_results_bucket_name = module.storage.athena_results_bucket_name
  lambda_code_bucket_name    = module.storage.lambda_code_bucket_name

  # Empty by default; the owner sets their own users in a gitignored tfvars.
  personal_iam_users = var.personal_iam_users

  # PR-010: the lambda name now comes from the etl-lambda module (same value as the
  # old default, so the narrowed InvokeFunction grant is unchanged).
  extractor_lambda_name = module.etl_lambda.extractor_lambda_name
}

# --- PR-010: etl-lambda (extractor function) ---
module "etl_lambda" {
  source      = "./modules/etl-lambda"
  environment = var.environment
  region      = var.aws_region

  lambda_code_bucket = module.storage.lambda_code_bucket_name
  lambda_zip_key     = "lambda_package.zip"
  lambda_zip_path    = var.lambda_zip_path

  lambda_exec_role_arn = module.iam.lambda_exec_role_arn

  partitioned_bucket_name = module.storage.partitioned_bucket_name
  simple_bucket_name      = module.storage.simple_bucket_name
  secret_name             = var.lottery_secret_name
}

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
