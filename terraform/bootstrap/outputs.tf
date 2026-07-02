output "state_bucket_name" {
  description = "Name of the S3 bucket holding Terraform remote state. Copy into ../backend.hcl as `bucket`."
  value       = aws_s3_bucket.tf_state.id
}

output "lock_table_name" {
  description = "Name of the DynamoDB table used for state locking. Copy into ../backend.hcl as `dynamodb_table`."
  value       = aws_dynamodb_table.tf_locks.name
}
