# -----------------------------
# SageMaker Studio Domain
# -----------------------------
resource "aws_sagemaker_domain" "lottery_domain" {
  domain_name = "lottery-sagemaker-${var.environment}"
  auth_mode   = "IAM"
  # PR-008: the network module moved to the main stack (terraform/). These IDs are the
  # same live resources, hard-coded here as literals so the legacy stack still validates
  # and plans no-op. PR-015 moves sagemaker to a module and wires module.network outputs.
  vpc_id                  = "vpc-0fadac4b71ca76304"
  app_network_access_type = "VpcOnly"

  # Attach both private subnets where S3 endpoint was injected
  subnet_ids = [
    "subnet-09ef51bcc7e17e8e7", # priv-subnet-a-prod
    "subnet-0419da5b53dba0caf"  # priv-subnet-b-prod
  ]

  default_user_settings {
    execution_role  = var.lottery_sagemaker_execution_role_prod_arn
    security_groups = ["sg-0972cb28f1deb67a8"] # sm-studio-sg-prod


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

# -----------------------------
# SageMaker User Profile
# -----------------------------
# TODO PR-015: aws_sagemaker_user_profile import fails with "arn: invalid prefix" on
# aws provider v5.x (provider read-back bug, not a config issue). Left commented out so
# `terraform plan` stays a no-op during the PR-004 state reconstruction. The domain
# above imported fine. PR-015 makes SageMaker an opt-in module and can re-add this.
# resource "aws_sagemaker_user_profile" "lottery_user" {
#   domain_id         = aws_sagemaker_domain.lottery_domain.id
#   user_profile_name = "lottery-analyst"
#
#   user_settings {
#     execution_role = var.lottery_sagemaker_execution_role_prod_arn
#   }
# }
