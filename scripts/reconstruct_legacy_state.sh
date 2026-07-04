#!/usr/bin/env bash
#
# reconstruct_legacy_state.sh — PR-004 (adjusted)
#
# The legacy Terraform state for terraform-lottery/Prod was LOST (never committed,
# gitignored, no local copy). The resources still exist in AWS. This script rebuilds
# the state by `terraform import`-ing every importable resource into a fresh
# remote-backed state, so that `terraform plan` becomes a no-op.
#
# It is IDEMPOTENT: resources already in state are skipped, so re-running is safe.
#
# Run from terraform-lottery/Prod AFTER `terraform init` against the S3 backend.
# See docs/runbooks/PR-004-state-migration.md for the full procedure.
#
# Required env:
#   AWS_PROFILE   your prod profile
#   AWS_REGION    e.g. us-east-1
#   ENV           deploy environment suffix used in resource names (default: prod)
#
set -euo pipefail

ENV="${ENV:-prod}"
: "${AWS_REGION:?set AWS_REGION}"
ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
echo "Account: ${ACCOUNT_ID}  Region: ${AWS_REGION}  Env: ${ENV}"

# imp <terraform_address> <import_id> — import only if not already in state.
imp() {
  local addr="$1" id="$2"
  if terraform state list 2>/dev/null | grep -qxF "$addr"; then
    echo "  = already in state: $addr"
  else
    echo "  + importing: $addr  <-  $id"
    terraform import "$addr" "$id"
  fi
}

# lookup <aws-cli-command...> — echo a single ID, fail loudly if empty/None.
lookup() {
  local out
  out="$("$@")"
  if [[ -z "$out" || "$out" == "None" ]]; then
    echo "!! lookup returned empty for: $*" >&2
    return 1
  fi
  echo "$out"
}

pol="arn:aws:iam::${ACCOUNT_ID}:policy"        # customer-managed policy ARN prefix
awspol="arn:aws:iam::aws:policy"               # AWS-managed policy ARN prefix

echo "== S3 buckets + sub-resources =="
imp aws_s3_bucket.lambda_code_zip                                 "lambda-code-zip-${ENV}"
imp aws_s3_bucket.athena_results                                  "lottery-athena-results-${ENV}"
imp aws_s3_bucket_public_access_block.athena_results             "lottery-athena-results-${ENV}"
imp aws_s3_bucket_server_side_encryption_configuration.athena_results "lottery-athena-results-${ENV}"
imp aws_s3_bucket_lifecycle_configuration.athena_results         "lottery-athena-results-${ENV}"
imp aws_s3_object.lambda_package                                 "lambda-code-zip-${ENV}/lambda_package.zip"

echo "== Athena =="
imp aws_athena_workgroup.lottery_wg                              "lottery-wg"

echo "== Lambda =="
imp aws_lambda_function.extractor_lambda                         "lottery-extractor-${ENV}"

echo "== Glue =="
imp aws_glue_catalog_database.lottery_db                         "${ACCOUNT_ID}:lottery_santalucia_db"
imp aws_glue_job.lottery_transform                              "lottery-transform-${ENV}"
imp aws_glue_crawler.premios_crawler                           "lottery-premios-crawler"
imp aws_glue_crawler.sorteos_crawler                           "lottery-sorteos-crawler"
imp aws_glue_crawler.premios_silver_crawler                   "lottery-premios-silver-crawler"
imp aws_glue_crawler.sorteos_silver_crawler                   "lottery-sorteos-silver-crawler"

echo "== Step Functions =="
imp aws_sfn_state_machine.pipeline_state_machine \
  "arn:aws:states:${AWS_REGION}:${ACCOUNT_ID}:stateMachine:lottery-etl-pipeline-${ENV}"

echo "== EventBridge rules + targets (default bus) =="
imp aws_cloudwatch_event_rule.weekly_etl_trigger              "default/lottery-etl-weekly-trigger-${ENV}"
imp aws_cloudwatch_event_rule.weekly_trigger                 "default/weekly-etl-lottery-trigger-${ENV}"
imp aws_cloudwatch_event_target.trigger_step_function        "default/lottery-etl-weekly-trigger-${ENV}/StepFunctionLotteryETL"
imp aws_cloudwatch_event_target.trigger_state_machine        "default/weekly-etl-lottery-trigger-${ENV}/start-lottery-etl-pipeline"

echo "== Lake Formation =="
# aws_lakeformation_resource does NOT support `terraform import` (provider limitation).
# It was set up manually and stays manually-managed for now; PR-013 codifies Lake
# Formation properly. Comment out the resource block in lake_formation.tf (# TODO PR-013)
# so `terraform plan` doesn't try to CREATE it.
# imp aws_lakeformation_resource.athena_results_location      "arn:aws:s3:::lottery-athena-results-${ENV}"
echo "  ~ skipped aws_lakeformation_resource.athena_results_location (no import support; see PR-013)"

echo "== IAM roles =="
imp aws_iam_role.sagemaker_execution_role                    "lottery-sagemaker-execution-role-${ENV}"
imp aws_iam_role.glue_crawler_role                          "glue-crawler-role"
imp aws_iam_role.glue_job_role                              "glue-lottery-transform-role-${ENV}"
imp aws_iam_role.lambda_exec                                "lottery-lambda-exec-role${ENV}"     # NOTE: no dash (name = ...role${env})
imp aws_iam_role.sfn_execution_role                         "sfn-lottery-execution-role-${ENV}"
imp aws_iam_role.eventbridge_to_sfn_role                    "eventbridge-to-sfn-role-${ENV}"

echo "== IAM customer-managed policies =="
imp aws_iam_policy.sagemaker_s3_read_policy                  "${pol}/lottery-sagemaker-s3-read-policy-${ENV}"
imp aws_iam_policy.glue_crawler_s3_policy                   "${pol}/glue-crawler-s3-access"
imp aws_iam_policy.glue_job_policy                          "${pol}/glue-lottery-transform-policy-${ENV}"
imp aws_iam_policy.athena_results_access                    "${pol}/athena-results-s3-access"
imp aws_iam_policy.lambda_custom                            "${pol}/lottery-lambda-custom${ENV}"  # NOTE: no dash
imp aws_iam_policy.sagemaker_studio_admin_policy            "${pol}/lottery-sagemaker-studio-admin-policy-${ENV}"
imp aws_iam_policy.sfn_execution_policy                     "${pol}/sfn-lottery-policy-${ENV}"
imp aws_iam_policy.eventbridge_to_sfn_policy                "${pol}/eventbridge-to-sfn-policy-${ENV}"

echo "== IAM role_policy_attachments (id = role-name/policy-arn) =="
imp aws_iam_role_policy_attachment.glue_attach_policy        "glue-lottery-transform-role-${ENV}/${pol}/glue-lottery-transform-policy-${ENV}"
imp aws_iam_role_policy_attachment.lambda_basic             "lottery-lambda-exec-role${ENV}/${awspol}/service-role/AWSLambdaBasicExecutionRole"
imp aws_iam_role_policy_attachment.sagemaker_s3_read_attach "lottery-sagemaker-execution-role-${ENV}/${pol}/lottery-sagemaker-s3-read-policy-${ENV}"
imp aws_iam_role_policy_attachment.sagemaker_admin_policy_attach "lottery-sagemaker-execution-role-${ENV}/${pol}/lottery-sagemaker-studio-admin-policy-${ENV}"
imp aws_iam_role_policy_attachment.sagemaker_full_access    "lottery-sagemaker-execution-role-${ENV}/${awspol}/AmazonSageMakerFullAccess"
imp aws_iam_role_policy_attachment.cloudwatch_logs_full_access "lottery-sagemaker-execution-role-${ENV}/${awspol}/CloudWatchLogsFullAccess"
imp aws_iam_role_policy_attachment.attach_glue_s3           "glue-crawler-role/${pol}/glue-crawler-s3-access"
imp aws_iam_role_policy_attachment.lambda_custom_attach     "lottery-lambda-exec-role${ENV}/${pol}/lottery-lambda-custom${ENV}"
imp aws_iam_role_policy_attachment.sfn_execution_policy_attachment "sfn-lottery-execution-role-${ENV}/${pol}/sfn-lottery-policy-${ENV}"
imp aws_iam_role_policy_attachment.eventbridge_to_sfn_policy_attachment "eventbridge-to-sfn-role-${ENV}/${pol}/eventbridge-to-sfn-policy-${ENV}"

echo "== IAM user_policy_attachments (id = user-name/policy-arn) =="
imp aws_iam_user_policy_attachment.attach_results_user_dev    "santa-lucia-dev/${pol}/athena-results-s3-access"
imp aws_iam_user_policy_attachment.attach_results_user_adming "angel-adming/${pol}/athena-results-s3-access"

echo "== Network (IDs looked up by Name tag) =="
VPC_ID=$(lookup aws ec2 describe-vpcs --filters "Name=tag:Name,Values=lottery-vpc-${ENV}" --query 'Vpcs[0].VpcId' --output text)
SUB_A=$(lookup aws ec2 describe-subnets --filters "Name=tag:Name,Values=priv-subnet-a-${ENV}" --query 'Subnets[0].SubnetId' --output text)
SUB_B=$(lookup aws ec2 describe-subnets --filters "Name=tag:Name,Values=priv-subnet-b-${ENV}" --query 'Subnets[0].SubnetId' --output text)
SUB_PUB=$(lookup aws ec2 describe-subnets --filters "Name=tag:Name,Values=pub-subnet-${ENV}" --query 'Subnets[0].SubnetId' --output text)
RT_PUB=$(lookup aws ec2 describe-route-tables --filters "Name=tag:Name,Values=rt-public-${ENV}" --query 'RouteTables[0].RouteTableId' --output text)
RT_PRIV=$(lookup aws ec2 describe-route-tables --filters "Name=tag:Name,Values=rt-private-${ENV}" --query 'RouteTables[0].RouteTableId' --output text)
VPCE_S3=$(lookup aws ec2 describe-vpc-endpoints --filters "Name=tag:Name,Values=vpce-s3-${ENV}" --query 'VpcEndpoints[0].VpcEndpointId' --output text)
SG_SM=$(lookup aws ec2 describe-security-groups --filters "Name=group-name,Values=sm-studio-sg-${ENV}" --query 'SecurityGroups[0].GroupId' --output text)

imp aws_vpc.lottery                        "$VPC_ID"
imp aws_subnet.private_a                   "$SUB_A"
imp aws_subnet.private_b                   "$SUB_B"
imp aws_subnet.public                      "$SUB_PUB"
imp aws_route_table.public_rt              "$RT_PUB"
imp aws_route_table.private_rt             "$RT_PRIV"
imp aws_route_table_association.public_assoc    "${SUB_PUB}/${RT_PUB}"
imp aws_route_table_association.private_a_assoc "${SUB_A}/${RT_PRIV}"
imp aws_route_table_association.private_b_assoc "${SUB_B}/${RT_PRIV}"
imp aws_vpc_endpoint.s3                    "$VPCE_S3"
imp aws_security_group.sagemaker_studio    "$SG_SM"

# NAT path resources are count-gated behind var.enable_internet (default false).
# Only import them if you deployed with enable_internet = true.
if [[ "${ENABLE_INTERNET:-false}" == "true" ]]; then
  echo "== NAT path (enable_internet = true) =="
  IGW=$(lookup aws ec2 describe-internet-gateways --filters "Name=tag:Name,Values=lottery-igw-${ENV}" --query 'InternetGateways[0].InternetGatewayId' --output text)
  EIP=$(lookup aws ec2 describe-addresses --filters "Name=tag:Name,Values=lottery-nat-eip-${ENV}" --query 'Addresses[0].AllocationId' --output text)
  NAT=$(lookup aws ec2 describe-nat-gateways --filter "Name=tag:Name,Values=lottery-nat-${ENV}" --query 'NatGateways[0].NatGatewayId' --output text)
  imp 'aws_internet_gateway.igw[0]' "$IGW"
  imp 'aws_eip.nat_eip[0]'          "$EIP"
  imp 'aws_nat_gateway.nat[0]'      "$NAT"
  imp 'aws_route.public_defautl[0]' "${RT_PUB}_0.0.0.0/0"
  imp 'aws_route.private_default[0]' "${RT_PRIV}_0.0.0.0/0"
else
  echo "== Skipping NAT path (enable_internet = false) =="
fi

echo "== SageMaker =="
SM_DOMAIN=$(lookup aws sagemaker list-domains --query "Domains[?DomainName=='lottery-sagemaker-${ENV}'].DomainId | [0]" --output text)
imp aws_sagemaker_domain.lottery_domain            "$SM_DOMAIN"
# aws_sagemaker_user_profile import fails with "arn: invalid prefix" during read-back
# on aws provider v5.x (provider bug, not a config issue). Comment out the resource in
# sagemaker.tf (# TODO PR-015) — SageMaker becomes an opt-in module there anyway.
# imp aws_sagemaker_user_profile.lottery_user      "${SM_DOMAIN}/lottery-analyst"
echo "  ~ skipped aws_sagemaker_user_profile.lottery_user (provider import bug; see PR-015)"

echo
echo "Done importing. NOT imported (Terraform cannot import these — see runbook):"
echo "  - null_resource.run_glue_crawlers                  (PR-012)"
echo "  - null_resource.run_silver_glue_crawlers           (PR-012)"
echo "  - aws_iam_policy_attachment.glue_service_policy    (PR-009)"
echo "  - aws_lakeformation_resource.athena_results_location (PR-013, no import support)"
echo "  - aws_sagemaker_user_profile.lottery_user          (PR-015, provider import bug)"
echo
echo "Next: run 'terraform plan'. Expect a NO-OP except (optionally) the 3 above."
echo "See docs/runbooks/PR-004-state-migration.md for how to handle them."
