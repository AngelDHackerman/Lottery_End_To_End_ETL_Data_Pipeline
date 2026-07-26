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

  # PR-011: same story for the glue job name.
  glue_job_name = module.etl_glue.glue_job_name

  # PR-012: and for the silver crawler names.
  glue_crawler_premios_name = module.catalog.premios_silver_crawler_name
  glue_crawler_sorteos_name = module.catalog.sorteos_silver_crawler_name

  # PR-022: scope the SFN role's gold CTAS grants (glue tables + athena workgroup).
  database_name         = module.catalog.db_name
  athena_workgroup_name = module.catalog.athena_workgroup_name
}

# --- PR-010: etl-lambda (extractor function) ---
module "etl_lambda" {
  source      = "./modules/etl-lambda"
  environment = var.environment
  region      = var.aws_region

  lambda_code_bucket = module.storage.lambda_code_bucket_name
  lambda_zip_key     = "lambda_package.zip"
  lambda_zip_path    = var.lambda_zip_path

  # PR-019: deps ship in a layer, so the zip above is code-only.
  lambda_layer_zip_key  = "lambda_layer.zip"
  lambda_layer_zip_path = var.lambda_layer_zip_path

  lambda_exec_role_arn = module.iam.lambda_exec_role_arn

  partitioned_bucket_name = module.storage.partitioned_bucket_name
  simple_bucket_name      = module.storage.simple_bucket_name
  secret_name             = var.lottery_secret_name

  # PR-023: own the function's log group so it has a retention policy.
  log_retention_days = var.log_retention_days
}

# --- PR-011: etl-glue (transform job; script_location parameterized) ---
module "etl_glue" {
  source      = "./modules/etl-glue"
  environment = var.environment

  code_bucket = module.storage.lambda_code_bucket_name
  script_key  = "lottery_transformer.zip"

  glue_job_role_arn = module.iam.glue_job_role_arn

  partitioned_bucket_name = module.storage.partitioned_bucket_name
  simple_bucket_name      = module.storage.simple_bucket_name
  secret_name             = var.lottery_secret_name

  # PR-023: retention on the ACCOUNT-WIDE Python Shell log groups (Glue has no per-job
  # group for pythonshell — see the module note).
  log_retention_days            = var.log_retention_days
  manage_shared_glue_log_groups = var.manage_shared_glue_log_groups
}

# --- PR-012: catalog (Glue DB + silver crawlers + Athena workgroup) ---
module "catalog" {
  source      = "./modules/catalog"
  environment = var.environment

  glue_crawler_role_arn = module.iam.glue_crawler_role_arn

  partitioned_bucket_name    = module.storage.partitioned_bucket_name
  athena_results_bucket_name = module.storage.athena_results_bucket_name

  # PR-023: retention on the ACCOUNT-WIDE /aws-glue/crawlers group.
  log_retention_days            = var.log_retention_days
  manage_shared_glue_log_groups = var.manage_shared_glue_log_groups
}

# --- PR-012: orchestration (Step Functions + single weekly EventBridge trigger) ---
module "orchestration" {
  source      = "./modules/orchestration"
  environment = var.environment

  sfn_execution_role_arn      = module.iam.sfn_execution_role_arn
  eventbridge_to_sfn_role_arn = module.iam.eventbridge_to_sfn_role_arn

  extractor_lambda_arn = module.etl_lambda.extractor_lambda_arn
  glue_job_name        = module.etl_glue.glue_job_name
  premios_crawler_name = module.catalog.premios_silver_crawler_name
  sorteos_crawler_name = module.catalog.sorteos_silver_crawler_name

  # PR-022: Gold layer — upload sql/gold/, run the purge Lambda + CTAS Map.
  partitioned_bucket_name    = module.storage.partitioned_bucket_name
  database_name              = module.catalog.db_name
  athena_workgroup_name      = module.catalog.athena_workgroup_name
  gold_purge_lambda_role_arn = module.iam.gold_purge_lambda_role_arn

  # PR-023: gold-purge log group + NEW Step Functions execution logging.
  log_retention_days         = var.log_retention_days
  sfn_log_level              = var.sfn_log_level
  sfn_include_execution_data = var.sfn_include_execution_data

  # PR-023: the ONLY reference into module.iam above is the role's *ARN*, which creates no
  # edge to aws_iam_policy.sfn_execution_policy — so Terraform is free to update the state
  # machine in parallel with (or before) the policy that grants it log-delivery rights.
  # Step Functions validates logging_configuration during UpdateStateMachine and fails with
  # `AccessDeniedException: ... not authorized to perform: logs:CreateLogDelivery` when the
  # role isn't ready yet. Observed as a retry-and-it-works flake on the PR-023 apply; this
  # makes the ordering explicit so a fresh deploy doesn't depend on luck.
  depends_on = [module.iam]
}

# --- PR-013: lake-formation (permissions so crawlers need no console clicks) ---
module "lake_formation" {
  source = "./modules/lake-formation"

  partitioned_bucket_arn = module.storage.partitioned_bucket_arn
  glue_crawler_role_arn  = module.iam.glue_crawler_role_arn
  database_name          = module.catalog.db_name

  # PR-022: gold automation roles need LF grants (DROP for purge, CREATE_TABLE for CTAS).
  sfn_execution_role_arn     = module.iam.sfn_execution_role_arn
  gold_purge_lambda_role_arn = module.iam.gold_purge_lambda_role_arn

  enable_iam_allowed_principals_compat = var.enable_iam_allowed_principals_compat
}

# --- PR-014: observability (SNS alerts; dashboards/alarms added PR-024..PR-028) ---
module "observability" {
  source      = "./modules/observability"
  environment = var.environment
  alert_email = var.alert_email
}

# --- PR-015: sagemaker (optional; gated so a fresh cloner gets nothing) ---
module "sagemaker" {
  source      = "./modules/sagemaker"
  count       = var.enable_sagemaker ? 1 : 0
  environment = var.environment

  vpc_id            = module.network.vpc_id
  subnet_ids        = module.network.private_subnet_ids
  security_group_id = module.network.sagemaker_sg_id

  sagemaker_execution_role_arn = module.iam.sagemaker_execution_role_arn
}
