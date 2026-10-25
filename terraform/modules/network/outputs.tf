# Outputs exposed by the "network" module.
# Consumed by any resource that needs to land in the VPC (the sagemaker module that
# used them was removed in PR-052).

output "vpc_id" {
  description = "ID of the lottery VPC."
  value       = aws_vpc.lottery.id
}

output "private_subnet_ids" {
  description = "IDs of the two private subnets (the S3-endpoint side)."
  value       = [aws_subnet.private_a.id, aws_subnet.private_b.id]
}

output "public_subnet_id" {
  description = "ID of the public subnet (NAT side, when enable_internet is on)."
  value       = aws_subnet.public.id
}

