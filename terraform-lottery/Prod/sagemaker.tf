# -----------------------------
# SageMaker Studio Domain
# -----------------------------
resource "aws_sagemaker_domain" "lottery_domain" {
  domain_name               = "lottery-sagemaker-${var.environment}"
  auth_mode                 = "IAM"
  vpc_id                    = aws_vpc.lottery.id
  app_network_access_type   = "VpcOnly"

  # Attach both private subnets where S3 endpoint was injected
  subnet_ids        = [
    aws_subnet.private_a.id,
    aws_subnet.private_b.id
  ]

  default_user_settings {
    execution_role    = var.lottery_sagemaker_execution_role_prod_arn
    security_groups   = [ aws_security_group.sagemaker_studio.id ]  # attach the security group
    

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
