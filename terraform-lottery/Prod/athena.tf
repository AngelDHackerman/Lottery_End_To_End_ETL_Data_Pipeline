resource "aws_athena_workgroup" "lottery_wg" {
  name = "lottery-wg"

  configuration {
    result_configuration {
      # Bucket moved to the storage module in PR-007; reference by literal name
      # (same value) so this legacy stack no longer depends on the moved resource.
      output_location = "s3://lottery-athena-results-${var.environment}/"
    }
  }
}
