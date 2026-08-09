# PR-027: per-medallion-layer S3 object counts as custom metrics.
#
# PR-024's dashboard answers "did the run work?". It cannot answer "did the lake grow?" —
# and those are different questions. A pipeline can go green every week while writing
# nothing new: the extractor re-scrapes a page it already has, the transformer rewrites the
# same partition, every stage succeeds. `AWS/States` shows a healthy run; the data is
# stagnant. A flat `raw/` line next to green executions is that failure, made visible.
#
# WHY THIS ISN'T FREE ALREADY. S3 publishes `NumberOfObjects` and `BucketSizeBytes` into
# `AWS/S3` at no cost — but only per BUCKET. All three medallion layers live in one bucket,
# so the free metrics cannot separate raw/ from silver/ from gold/. Counting by hand is the
# only way to get the breakdown, which is exactly why the roadmap scoped this as its own PR.
#
# The roadmap marks PR-027 "(Optional) ... skip if the dashboard already feels rich enough".
# Built anyway: every other widget on that dashboard is derived from an execution, so
# without this the dashboard has no measure of the ASSET the pipeline exists to produce.

locals {
  object_count_function_name = "lottery-object-count-${var.environment}"

  # Passed to the Lambda as a comma-separated env var. `processed/` is deliberately absent:
  # it is the orphaned legacy prefix from the crawlers PR-012 removed (267 objects, frozen),
  # so charting it would add a permanently flat line and $0.60/month of metrics for a
  # tombstone.
  object_count_prefix_csv = join(",", var.object_count_prefixes)
}

# PR-023 rule, and it is a real trap rather than a style point: declare the log group BEFORE
# the function. If the function is created first, Lambda auto-creates the group with no
# retention and Terraform then fails on ResourceAlreadyExistsException.
resource "aws_cloudwatch_log_group" "object_count" {
  count = var.enable_object_count_emitter ? 1 : 0

  name              = "/aws/lambda/${local.object_count_function_name}"
  retention_in_days = var.log_retention_days

  tags = {
    Name        = "/aws/lambda/${local.object_count_function_name}"
    Environment = var.environment
    Project     = "Lottery ETL"
    Owner       = "Angel Hackerman"
  }
}

# Single-file zip built by Terraform, same as the gold-purge Lambda: the only dependency is
# boto3, which the runtime already ships, so this skips the extractor's build pipeline
# (scripts/build_lambda_*.sh) entirely. Nothing here needs `make build`.
data "archive_file" "object_count" {
  count = var.enable_object_count_emitter ? 1 : 0

  type        = "zip"
  source_file = "${path.module}/../../../src/loteria/observability/object_count.py"
  output_path = "${path.module}/build/object_count.zip"
}

resource "aws_lambda_function" "object_count" {
  count = var.enable_object_count_emitter ? 1 : 0

  function_name    = local.object_count_function_name
  filename         = data.archive_file.object_count[0].output_path
  source_code_hash = data.archive_file.object_count[0].output_base64sha256
  handler          = "object_count.handler"
  runtime          = "python3.12"

  # 3 LIST calls against a few hundred keys — this finishes in well under a second. The
  # headroom is for the day a prefix crosses into multi-page territory; if it ever needs
  # more than 60 s, the answer is S3 Inventory, not a bigger timeout (see the module
  # docstring in object_count.py).
  timeout     = 60
  memory_size = 128

  role = var.object_count_lambda_role_arn

  environment {
    variables = {
      TARGET_BUCKET  = var.partitioned_bucket_name
      LAYER_PREFIXES = local.object_count_prefix_csv
      # Must equal the `cloudwatch:namespace` condition on this role's IAM policy. Both come
      # from the same Terraform variable, so they cannot drift — see the iam module's
      # `object_count_lambda_policy` for why a mismatch would fail silently.
      METRICS_NAMESPACE = var.metrics_namespace
    }
  }

  depends_on = [aws_cloudwatch_log_group.object_count]

  tags = {
    Name        = local.object_count_function_name
    Environment = var.environment
    Project     = "Lottery ETL"
    Owner       = "Angel Hackerman"
  }
}

# Hourly, per the roadmap. That is far more often than the data changes (the pipeline runs
# once a week), but the cost is a rounding error — 730 invocations of a 128 MB function that
# runs for under a second, plus ~2,200 LIST requests, is a few cents a month — and an hourly
# grain means a mid-week manual backfill or an accidental deletion shows up as a step in the
# chart rather than being averaged into a daily point.
resource "aws_cloudwatch_event_rule" "object_count_schedule" {
  count = var.enable_object_count_emitter ? 1 : 0

  name                = "lottery-object-count-schedule-${var.environment}"
  description         = "Hourly per-layer S3 object count for the ${var.environment} medallion bucket."
  schedule_expression = var.object_count_schedule_expression
}

resource "aws_cloudwatch_event_target" "object_count_lambda" {
  count = var.enable_object_count_emitter ? 1 : 0

  rule      = aws_cloudwatch_event_rule.object_count_schedule[0].name
  target_id = "ObjectCountLambda"
  arn       = aws_lambda_function.object_count[0].arn
}

# EventBridge invokes Lambda by resource policy, not by an execution role — without this the
# rule fires forever and the function never runs, with no error anywhere except the rule's
# FailedInvocations metric.
resource "aws_lambda_permission" "allow_eventbridge_object_count" {
  count = var.enable_object_count_emitter ? 1 : 0

  statement_id  = "AllowExecutionFromEventBridge"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.object_count[0].function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.object_count_schedule[0].arn
}
