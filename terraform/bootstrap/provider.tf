terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # NOTE: this bootstrap stack intentionally uses LOCAL state. It is the thing
  # that *creates* the remote backend, so it cannot depend on it. The main stack
  # (terraform/, PR-006) is what consumes the S3 backend produced here.
}

provider "aws" {
  region = var.aws_region
}
