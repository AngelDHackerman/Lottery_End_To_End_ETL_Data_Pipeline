# Module: sagemaker
# SageMaker Studio domain for EDA notebooks. OPT-IN: the root wraps this module in
# `count = var.enable_sagemaker ? 1 : 0` (default false) — a fresh cloner gets nothing.
# Migrated from terraform-lottery/Prod/sagemaker.tf in PR-015 via cross-state
# `terraform state rm` (legacy) + `terraform import` (here, only if enabled).
# See docs/runbooks/PR-015-sagemaker-and-legacy-teardown.md.

resource "aws_sagemaker_domain" "lottery_domain" {
  domain_name             = "lottery-sagemaker-${var.environment}"
  auth_mode               = "IAM"
  vpc_id                  = var.vpc_id
  app_network_access_type = "VpcOnly"

  # Both private subnets (the S3 gateway endpoint lives on their route table).
  subnet_ids = var.subnet_ids

  default_user_settings {
    execution_role  = var.sagemaker_execution_role_arn
    security_groups = [var.security_group_id]

    jupyter_server_app_settings {
      default_resource_spec {
        instance_type = "system"
      }
    }
  }

  tags = {
    Name = "lottery-sagemaker-${var.environment}"
  }
}

# TODO: aws_sagemaker_user_profile import fails with "arn: invalid prefix" on aws
# provider v5.x (provider read-back bug, noted since the PR-004 state reconstruction).
# The deployed "lottery-analyst" profile keeps existing unmanaged; re-add this once the
# provider bug is fixed (or when recreating the profile is acceptable).
# resource "aws_sagemaker_user_profile" "lottery_user" {
#   domain_id         = aws_sagemaker_domain.lottery_domain.id
#   user_profile_name = "lottery-analyst"
#
#   user_settings {
#     execution_role = var.sagemaker_execution_role_arn
#   }
# }
