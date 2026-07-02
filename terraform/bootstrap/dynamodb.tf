# DynamoDB table used by the S3 backend for state locking (prevents two
# concurrent `terraform apply` runs from corrupting state). PAY_PER_REQUEST so
# there is no idle cost — it is hit only during plan/apply.

resource "aws_dynamodb_table" "tf_locks" {
  name         = "loteria-tf-locks"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }

  tags = merge(local.common_tags, { Purpose = "terraform-state-lock" })
}
