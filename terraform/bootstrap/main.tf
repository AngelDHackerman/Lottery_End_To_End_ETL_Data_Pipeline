# Remote Terraform state bucket. Created ONCE by this bootstrap stack; the main
# stack (terraform/, PR-006) then points its S3 backend at this bucket. See README.md.

locals {
  common_tags = {
    Project   = "loteria-santa-lucia"
    ManagedBy = "terraform"
    Component = "tf-backend"
  }
}

resource "aws_s3_bucket" "tf_state" {
  bucket = "loteria-tf-state-${var.aws_account_id}"

  # This bucket holds the source of truth for all infrastructure state.
  # Losing it is catastrophic, so guard against accidental `terraform destroy`.
  lifecycle {
    prevent_destroy = true
  }

  tags = merge(local.common_tags, { Purpose = "terraform-remote-state" })
}

resource "aws_s3_bucket_versioning" "tf_state" {
  bucket = aws_s3_bucket.tf_state.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "tf_state" {
  bucket = aws_s3_bucket.tf_state.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "tf_state" {
  bucket = aws_s3_bucket.tf_state.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
