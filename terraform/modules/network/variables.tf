# Input variables for the "network" module.

variable "environment" {
  description = "Deployment environment suffix used in resource names (e.g. \"prod\")."
  type        = string
}

variable "aws_region" {
  description = "AWS region — used to build the S3 gateway VPC endpoint service name."
  type        = string
}

variable "aws_availability_zone_a" {
  description = "AZ for the first private subnet and the public subnet."
  type        = string
}

variable "aws_availability_zone_b" {
  description = "AZ for the second private subnet."
  type        = string
}

variable "enable_internet" {
  description = "Create the NAT/IGW/EIP + default-route egress path. Default off (private, S3-endpoint-only)."
  type        = bool
  default     = false
}
