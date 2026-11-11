terraform {
  required_version = ">= 1.7"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    # UY-044.3: the gold Lambda's zip (gold.tf), as the main stack builds its small Lambdas.
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}

provider "aws" {
  region = var.aws_region

  # Every UY resource says where it came from, so the console and Cost Explorer can tell it
  # apart from Santa Lucía's in the same account.
  default_tags {
    tags = {
      Project     = "Loteria-Uruguay"
      Country     = "uy"
      Environment = var.environment
      ManagedBy   = "terraform/uy"
    }
  }
}
