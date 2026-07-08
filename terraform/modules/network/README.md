# Module: `network`

VPC, subnets, route tables, NAT/IGW (gated by `var.enable_internet`), S3 gateway VPC
endpoint, and the SageMaker Studio security group.

**Status:** migrated from `terraform-lottery/Prod/network.tf` in **PR-008** via cross-state
`terraform state rm` (legacy) + `terraform import` (main) — no resource is recreated.
See [`docs/runbooks/PR-008-network-migration.md`](../../../docs/runbooks/PR-008-network-migration.md).

## Egress toggle
`enable_internet` defaults to **false**: the VPC is private and reaches S3 only through the
gateway endpoint. Flipping it to `true` creates the IGW, EIP, NAT gateway, and the two
default routes (`0.0.0.0/0`). These are currently NOT present in AWS.

## Inputs
- `environment` — name suffix (e.g. `prod`)
- `aws_region` — builds the S3 endpoint service name
- `aws_availability_zone_a` / `aws_availability_zone_b` — subnet AZs
- `enable_internet` — egress toggle (default false)

## Outputs
- `vpc_id`
- `private_subnet_ids` — `[private_a, private_b]`
- `public_subnet_id`
- `sagemaker_sg_id`
