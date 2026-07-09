# MOVED in PR-008 → terraform/modules/network/
#
# All networking resources that used to live here (aws_vpc.lottery, the two private
# subnets + public subnet, both route tables + associations, aws_vpc_endpoint.s3, and
# aws_security_group.sagemaker_studio — plus the enable_internet-gated IGW / EIP / NAT /
# default routes, which are OFF in prod and don't exist in AWS) were migrated to the
# network module via cross-state `terraform state rm` (here) + `terraform import` (into
# the main stack). No resource was recreated. See docs/runbooks/PR-008-network-migration.md.
#
# sagemaker.tf still references the VPC / subnets / SG; those are now hard-coded as literal
# IDs there (same live resources) until PR-015 moves sagemaker to a module.
#
# This file is intentionally left as a pointer; the whole terraform-lottery/Prod/ folder
# is deleted in PR-015 once every module has migrated.
