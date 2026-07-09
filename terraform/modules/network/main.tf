# Module: network
# VPC, subnets, route tables, S3 VPC endpoint, and the SageMaker security group.
# Migrated from terraform-lottery/Prod/network.tf in PR-008 via cross-state
# `terraform state rm` (legacy) + `terraform import` (here) — no resource is
# recreated. See docs/runbooks/PR-008-network-migration.md.
#
# The NAT / IGW / EIP / default-route egress path is gated by var.enable_internet
# (default false). It is currently OFF in prod, so those count-gated resources do
# not exist in AWS and are not imported — the module just carries the code so the
# path can be flipped on later without a structural change.

# Create main VPC for Lottery Proyect
resource "aws_vpc" "lottery" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags = {
    Name = "lottery-vpc-${var.environment}"
  }
}

# Subnets 2 private for SageMaker Studio, 1 public for NAT Gateway
resource "aws_subnet" "private_a" {
  vpc_id            = aws_vpc.lottery.id
  cidr_block        = "10.0.1.0/24"
  availability_zone = var.aws_availability_zone_a
  tags = {
    Name = "priv-subnet-a-${var.environment}"
  }
}

resource "aws_subnet" "private_b" {
  vpc_id            = aws_vpc.lottery.id
  cidr_block        = "10.0.2.0/24"
  availability_zone = var.aws_availability_zone_b
  tags = {
    Name = "priv-subnet-b-${var.environment}"
  }
}

resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.lottery.id
  cidr_block              = "10.0.3.0/24"
  map_public_ip_on_launch = true
  availability_zone       = var.aws_availability_zone_a
  tags = {
    Name = "pub-subnet-${var.environment}"
  }
}

# Internet Gateway
# Create and associate the VPC for public outbound traffic (if internet is enabled)
resource "aws_internet_gateway" "igw" {
  count  = var.enable_internet ? 1 : 0
  vpc_id = aws_vpc.lottery.id
  tags = {
    Name = "lottery-igw-${var.environment}"
  }
}

# NAT + EIP (if internet is enabled)
# In the public subnet with an Elastic IP.
# Allows private subnets to reach the internet
# (for pip installs, updates, or optionally reading S3 without an endpoint).

resource "aws_eip" "nat_eip" {
  count  = var.enable_internet ? 1 : 0
  domain = "vpc"
  tags = {
    Name = "lottery-nat-eip-${var.environment}"
  }
}

resource "aws_nat_gateway" "nat" {
  count         = var.enable_internet ? 1 : 0
  allocation_id = aws_eip.nat_eip[0].id
  subnet_id     = aws_subnet.public.id
  tags = {
    Name = "lottery-nat-${var.environment}"
  }
}

# Route Tables
# Public Table: 0.0.0.0/0 → igw
resource "aws_route_table" "public_rt" {
  vpc_id = aws_vpc.lottery.id
  tags = {
    Name = "rt-public-${var.environment}"
  }
}

resource "aws_route" "public_defautl" {
  count                  = var.enable_internet ? 1 : 0
  route_table_id         = aws_route_table.public_rt.id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.igw[0].id
}

resource "aws_route_table_association" "public_assoc" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public_rt.id
}

# Private table
resource "aws_route_table" "private_rt" {
  vpc_id = aws_vpc.lottery.id
  tags = {
    Name = "rt-private-${var.environment}"
  }
}
resource "aws_route" "private_default" {
  count                  = var.enable_internet ? 1 : 0
  route_table_id         = aws_route_table.private_rt.id
  destination_cidr_block = "0.0.0.0/0"
  nat_gateway_id         = aws_nat_gateway.nat[0].id
}
resource "aws_route_table_association" "private_a_assoc" {
  subnet_id      = aws_subnet.private_a.id
  route_table_id = aws_route_table.private_rt.id
}
resource "aws_route_table_association" "private_b_assoc" {
  subnet_id      = aws_subnet.private_b.id
  route_table_id = aws_route_table.private_rt.id
}

# VPC Endpoint Gateway S3
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.lottery.id
  service_name      = "com.amazonaws.${var.aws_region}.s3"
  vpc_endpoint_type = "Gateway"

  # injects a route to S3 into the private table
  route_table_ids = [aws_route_table.private_rt.id]

  tags = {
    Name = "vpce-s3-${var.environment}"
  }
}

# Security group para Sagemaker Studio
resource "aws_security_group" "sagemaker_studio" {
  name        = "sm-studio-sg-${var.environment}"
  description = "Allow Studio outbound HTTP/HTTPS; no inbound from internet"
  vpc_id      = aws_vpc.lottery.id

  # Input: None except internal traffic between instances of the same SG
  ingress {
    description = "Allow internal traffic between studio ENIs"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    self        = true
  }

  # Outbound HTTP
  egress {
    description      = "Allow HTTP out"
    from_port        = 80
    to_port          = 80
    protocol         = "tcp"
    cidr_blocks      = ["0.0.0.0/0"]
    ipv6_cidr_blocks = ["::/0"]
  }

  # Outboud HTTPS
  egress {
    description      = "Allow HTTPS out"
    from_port        = 443
    to_port          = 443
    protocol         = "tcp"
    cidr_blocks      = ["0.0.0.0/0"]
    ipv6_cidr_blocks = ["::/0"]
  }

  tags = {
    Name = "sm-studio-sg-${var.environment}"
  }
}
