# Module: storage
# The project's S3 buckets. Migrated from terraform-lottery/Prod/s3.tf in PR-007 via
# cross-state `terraform state rm` (legacy) + `terraform import` (here) — no bucket is
# recreated. See docs/runbooks/PR-007-storage-migration.md.
#
# Holds:
#   - lottery_partitioned  (raw + silver + gold data; prevent_destroy)
#   - (lottery_simple was here — emptied and deleted by hand 2026-10-22, PR-041.3;
#     the `removed` blocks below drop it from state without touching AWS)
#   - lambda_code_zip      (Lambda deployment artifacts)
#   - athena_results       (Athena query output; force_destroy, 30-day expiry)

# ---------------------------------------------------------------------------
# PROD DATA BUCKETS (imported in PR-005, moved here in PR-007)
#
# Guardrails: prevent_destroy = true, NO force_destroy, versioning Enabled,
# SSE (AES256), full public-access block. The deny-delete bucket policy from
# PR-002 is intentionally NOT modeled here (stays as an out-of-band safety belt).
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

# PR-041.3 — lottery-data-simple-prod no longer exists. It was emptied (540 versions + 2
# delete markers) and deleted by the owner on 2026-10-22, by hand, because PR-002's Deny
# policy and prevent_destroy were there precisely so Terraform could never do it. These
# blocks only forget the four resources; `destroy = false` means no apply can reach AWS
# for them, whichever order the plan runs in. See docs/runbooks/PR-041-retire-simple-bucket.md.
removed {
  from = aws_s3_bucket.lottery_simple
  lifecycle {
    destroy = false
  }
}

removed {
  from = aws_s3_bucket_versioning.lottery_simple
  lifecycle {
    destroy = false
  }
}

removed {
  from = aws_s3_bucket_server_side_encryption_configuration.lottery_simple
  lifecycle {
    destroy = false
  }
}

removed {
  from = aws_s3_bucket_public_access_block.lottery_simple
  lifecycle {
    destroy = false
  }
}

# ---------------------------------------------------------------------------
# SUPPORTING BUCKETS
# ---------------------------------------------------------------------------

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
