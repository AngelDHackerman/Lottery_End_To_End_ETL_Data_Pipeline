# Outputs exposed by the "network" module.
# Consumed by the sagemaker module (PR-015) and any resource that needs to land
# in the VPC.

output "vpc_id" {
  description = "ID of the lottery VPC."
  value       = aws_vpc.lottery.id
}

output "private_subnet_ids" {
  description = "IDs of the two private subnets (SageMaker Studio / S3-endpoint side)."
  value       = [aws_subnet.private_a.id, aws_subnet.private_b.id]
}

output "public_subnet_id" {
  description = "ID of the public subnet (NAT side, when enable_internet is on)."
  value       = aws_subnet.public.id
}

output "sagemaker_sg_id" {
  description = "ID of the SageMaker Studio security group."
  value       = aws_security_group.sagemaker_studio.id
}
