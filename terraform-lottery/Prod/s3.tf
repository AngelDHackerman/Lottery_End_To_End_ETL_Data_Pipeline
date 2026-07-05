# ---------------------------------------------------------------------------
# PROD DATA BUCKETS (imported in PR-005)
#
# These two buckets hold the real, irreplaceable lottery data. They were created
# outside Terraform and are brought under management via `terraform import`
# (see docs/runbooks/PR-005-bucket-import.md). The `${var.environment}` (= "prod")
# interpolation resolves to the exact deployed names:
#   lottery-partitioned-storage-prod  and  lottery-data-simple-prod
#
# Guardrails (per roadmap PR-005):
#   - prevent_destroy = true          -> Terraform refuses to delete them.
#   - NO force_destroy                -> never allow a non-empty-bucket delete.
#   - versioning Enabled              -> already turned on in PR-002; import = no-op.
#   - SSE (AES256) + public access block.
#
# The deny-delete bucket policy applied in PR-002 is intentionally NOT modeled here,
# so Terraform will not touch it. It stays as an out-of-band safety belt.
# ---------------------------------------------------------------------------

# Bucket for raw + partitioned data (.txt raw, silver/gold parquet)
resource "aws_s3_bucket" "lottery_partitioned" {
  bucket = "lottery-partitioned-storage-${var.environment}"

  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Name        = "lottery-partitioned-storage-${var.environment}"
    Environment = var.environment
    Owner       = "Angel Hackerman"
    Project     = "Lottery ETL"
  }
}

resource "aws_s3_bucket_versioning" "lottery_partitioned" {
  bucket = aws_s3_bucket.lottery_partitioned.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "lottery_partitioned" {
  bucket = aws_s3_bucket.lottery_partitioned.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "lottery_partitioned" {
  bucket                  = aws_s3_bucket.lottery_partitioned.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Bucket for the simple / EDA-friendly dataset
resource "aws_s3_bucket" "lottery_simple" {
  bucket = "lottery-data-simple-${var.environment}"

  lifecycle {
    prevent_destroy = true
  }

  tags = {
    Name        = "lottery-simple-storage-${var.environment}"
    Environment = var.environment
    Owner       = "Angel Hackerman"
    Project     = "Lottery ETL"
  }
}

resource "aws_s3_bucket_versioning" "lottery_simple" {
  bucket = aws_s3_bucket.lottery_simple.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "lottery_simple" {
  bucket = aws_s3_bucket.lottery_simple.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "lottery_simple" {
  bucket                  = aws_s3_bucket.lottery_simple.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Bucket for Lambda code
resource "aws_s3_bucket" "lambda_code_zip" {
  bucket = "lambda-code-zip-${var.environment}"

  lifecycle {
    prevent_destroy = false
  }

  tags = {
    Name        = "lambda-code-zip-${var.environment}"
    Environment = var.environment
    Owner       = "Angel Hackerman"
    Project     = "Lottery ETL"
  }
}

# Bucket for Athena results
resource "aws_s3_bucket" "athena_results" {
  bucket        = "lottery-athena-results-${var.environment}"
  force_destroy = true
  tags = {
    Name = "Athena Query Resutls"
  }
}

# Block public access 
resource "aws_s3_bucket_public_access_block" "athena_results" {
  bucket                  = aws_s3_bucket.athena_results.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Encryption using SSE-S3
resource "aws_s3_bucket_server_side_encryption_configuration" "athena_results" {
  bucket = aws_s3_bucket.athena_results.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Remove results after 30 days
resource "aws_s3_bucket_lifecycle_configuration" "athena_results" {
  bucket = aws_s3_bucket.athena_results.id
  rule {
    id     = "expire-athena-results"
    status = "Enabled"
    filter {}
    expiration {
      days = 30
    }
  }
}