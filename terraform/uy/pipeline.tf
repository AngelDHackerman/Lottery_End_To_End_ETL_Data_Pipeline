# The nightly pipeline (UY-043.3.1). DESIGN.md D16, D27; roadmap UY-043.
#
#   Defaults -> CheckInput -> Fetch (lambda fetch, mode=incremental) -> Silver (pending + finalize)
#            -> ValidateSilver (the GX Glue job, dq.tf; UY-043.4)
#            -> BuildGold (lambda gold, gold.tf; UY-044.3), skipped in a dry run
#
# The definition lives in pipeline.asl.json.tftpl so a unit test can render and check it without
# AWS (tests/unit/sorteos/test_uy_pipeline_asl.py); `make uy-tf-plan` also validates the rendered
# one against the Step Functions API (scripts/uy_sfn_validate.py: master's lesson, a definition
# built by Terraform is only proven by AWS).
#
# Started every night at 23:30 Montevideo by the EventBridge Scheduler at the bottom (D27,
# UY-043.3.2), which lands together with the switch-off of the local incremental (`make
# uy-incremental` refuses without UY_LOCAL=1): one writer on the manifest, as G4 requires.
#
# No crawler step: the silver tables are declared with projected partitions (catalog.tf, D31).
#
# ValidateSilver fails the execution when an expectation fails (owner, UY-043.4 3a): the alarm
# below sends the e-mail and the night counts as a failure for G4. Silver is already written by
# then; what the gate protects is gold, which is never built on a silver that failed. BuildGold
# fails the execution the same way (owner, UY-044.3 2a): published gold stays last night's.

locals {
  state_machine_name = "lottery-uy-pipeline-${var.environment}"
  # Step Functions' vended logs: the group name MUST start with /aws/vendedlogs/ (PR-023).
  state_machine_log_group = "/aws/vendedlogs/states/${local.state_machine_name}"

  # fetch: 900 s; silver: 900 s plus one retry after 60 s; the DQ job: var.dq_timeout_minutes
  # (10 at most, 600 s); gold: var.gold_timeout_seconds (180 at most). Lambda's own
  # service-error retries are seconds. An hour is above the worst case (3,540 s) and still
  # ends a stuck run the same night.
  execution_timeout_seconds = 3600
}

# Declared before the state machine (PR-023), with the same retention as the Lambdas'.
resource "aws_cloudwatch_log_group" "pipeline" {
  #checkov:skip=CKV_AWS_158:no secrets in these logs; the AWS managed key is enough
  name              = local.state_machine_log_group
  retention_in_days = var.log_retention_days
}

data "aws_iam_policy_document" "states_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
    # The confused-deputy guard: only a state machine of this account may assume the role.
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_iam_role" "pipeline" {
  name               = "lottery-uy-pipeline-sfn-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.states_assume.json
}

data "aws_iam_policy_document" "pipeline" {
  # The two functions, and their qualified forms (`:version` / `:alias`): lambda:invoke may
  # address either, and IAM matches the ARN as written.
  statement {
    sid     = "InvokeUyLambdas"
    effect  = "Allow"
    actions = ["lambda:InvokeFunction"]
    resources = [
      aws_lambda_function.fetch.arn,
      "${aws_lambda_function.fetch.arn}:*",
      aws_lambda_function.silver.arn,
      "${aws_lambda_function.silver.arn}:*",
      aws_lambda_function.gold.arn,
      "${aws_lambda_function.gold.arn}:*",
    ]
  }

  # glue:startJobRun.sync: Step Functions starts the run, polls it and, if the execution is
  # stopped, stops it. Only this job.
  statement {
    sid    = "RunSilverDqJob"
    effect = "Allow"
    actions = [
      "glue:StartJobRun",
      "glue:GetJobRun",
      "glue:GetJobRuns",
      "glue:BatchStopJobRun",
    ]
    resources = [aws_glue_job.silver_dq.arn]
  }

  # Step Functions delivers its logs through CloudWatch Logs' vended-logs API, whose actions do
  # not support resource-level permissions: "*" is the service's constraint (PR-023), not a
  # shortcut.
  statement {
    sid    = "DeliverExecutionLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogDelivery",
      "logs:GetLogDelivery",
      "logs:UpdateLogDelivery",
      "logs:DeleteLogDelivery",
      "logs:ListLogDeliveries",
      "logs:PutResourcePolicy",
      "logs:DescribeResourcePolicies",
      "logs:DescribeLogGroups",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "pipeline" {
  name   = "lottery-uy-pipeline-sfn-${var.environment}"
  role   = aws_iam_role.pipeline.id
  policy = data.aws_iam_policy_document.pipeline.json
}

resource "aws_sfn_state_machine" "pipeline" {
  #checkov:skip=CKV_AWS_284:no X-Ray anywhere in the repo; each step's report is in the execution history and the logs
  name     = local.state_machine_name
  role_arn = aws_iam_role.pipeline.arn
  type     = "STANDARD" # up to an hour per run, once a night: Express caps at 5 minutes

  definition = templatefile("${path.module}/pipeline.asl.json.tftpl", {
    fetch_function_arn  = aws_lambda_function.fetch.arn
    silver_function_arn = aws_lambda_function.silver.arn
    # Written out, not read from the resource, for the same reason as dq_job_name below: a
    # new function's ARN is unknown at plan time and the definition could not be validated.
    gold_function_arn = "arn:aws:lambda:${var.aws_region}:${local.account_id}:function:${local.gold_function_name}"
    # The name from the local, not from the resource: it is known at plan time, so `make
    # uy-tf-plan` can validate the definition before the job exists. depends_on gives the order.
    dq_job_name               = local.dq_job_name
    execution_timeout_seconds = local.execution_timeout_seconds
  })

  # ALL with the execution data: the input is one boolean and each report is counts and bronze
  # keys, no secret and no coupon (C7). That is what makes a failed night readable.
  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.pipeline.arn}:*"
    include_execution_data = true
    level                  = "ALL"
  }

  # Step Functions checks the role can deliver logs when it creates or updates the machine. The
  # role ARN alone gives no edge to its policy, and master's PR-023 apply failed on exactly that
  # race (AccessDeniedException on the log destination).
  depends_on = [aws_iam_role_policy.pipeline, aws_glue_job.silver_dq, aws_lambda_function.gold]
}

# --- The failure alarm (owner, UY-043.3 3a) -------------------------------------------------
#
# G4 counts nights with no manual intervention, so a failed or timed-out night has to reach
# someone. The topic is Santa Lucía's (module.observability), read here, never managed: the same
# inbox for both countries. A CloudWatch alarm needs no topic-policy grant in its own account.
#
# Hourly and notBreaching: a night with no run publishes nothing, which is not a failure (a
# missed night is UY-045's dead-man alarm). The alarm goes back to OK an hour later, so the
# e-mail is the signal, not the console (master's PR-025 lesson); no ok_actions, or every failure
# mails twice.

data "aws_sns_topic" "alerts" {
  name = "loteria-alerts-${var.environment}"
}

resource "aws_cloudwatch_metric_alarm" "pipeline_failed" {
  alarm_name          = "${local.state_machine_name}-failed"
  alarm_description   = "The UY nightly pipeline (${local.state_machine_name}) failed or timed out (a failed silver gate, ValidateSilver, is one way). Open the execution in the Step Functions console, or ${local.state_machine_log_group}. The next night catches up on its own (UY-043.3)."
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = 1
  evaluation_periods  = 1
  treat_missing_data  = "notBreaching"
  alarm_actions       = [data.aws_sns_topic.alerts.arn]

  metric_query {
    id          = "failures"
    expression  = "FILL(failed, 0) + FILL(timed_out, 0)"
    label       = "Failed or timed-out executions"
    return_data = true
  }

  metric_query {
    id = "failed"
    metric {
      namespace   = "AWS/States"
      metric_name = "ExecutionsFailed"
      dimensions  = { StateMachineArn = aws_sfn_state_machine.pipeline.arn }
      period      = 3600
      stat        = "Sum"
    }
  }

  metric_query {
    id = "timed_out"
    metric {
      namespace   = "AWS/States"
      metric_name = "ExecutionsTimedOut"
      dimensions  = { StateMachineArn = aws_sfn_state_machine.pipeline.arn }
      period      = 3600
      stat        = "Sum"
    }
  }
}

# --- The nightly schedule (UY-043.3.2, D27) --------------------------------------------------
#
# EventBridge Scheduler, not an EventBridge rule: rules only speak UTC, and the Scheduler keeps
# 23:30 in Montevideo even if Uruguay brings daylight saving back (D27).
#
# No retries (owner, UY-043.3 3a): a night that fails to start is caught up by the next one,
# since the fetch window starts the day after the manifest's last `resultados`. A failed run is
# the alarm above; a night that never started is UY-045's dead-man alarm.

data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
    # Only this account's schedules (the confused-deputy guard, as for the state machine's role).
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account_id]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "lottery-uy-scheduler-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
}

data "aws_iam_policy_document" "scheduler" {
  statement {
    sid       = "StartUyPipeline"
    effect    = "Allow"
    actions   = ["states:StartExecution"]
    resources = [aws_sfn_state_machine.pipeline.arn]
  }
}

resource "aws_iam_role_policy" "scheduler" {
  name   = "lottery-uy-scheduler-${var.environment}"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler.json
}

resource "aws_scheduler_schedule" "nightly" {
  #checkov:skip=CKV_AWS_297:the input is {"dry_run": false}; nothing for a customer key to protect
  name        = "lottery-uy-nightly-${var.environment}"
  description = "Starts ${local.state_machine_name} every night at 23:30 Montevideo (UY-043.3.2, D27)."

  schedule_expression          = "cron(30 23 * * ? *)"
  schedule_expression_timezone = "America/Montevideo"

  flexible_time_window {
    mode = "OFF"
  }

  target {
    arn      = aws_sfn_state_machine.pipeline.arn
    role_arn = aws_iam_role.scheduler.arn
    # Explicit, though Defaults turns {} into the same: the console shows what a night asks for.
    input = jsonencode({ dry_run = false })

    retry_policy {
      maximum_retry_attempts       = 0
      maximum_event_age_in_seconds = 60 # the API's minimum; with no retries it never matters
    }
  }

  # role_arn gives no edge to the role's policy: without this, a schedule created in the same
  # apply could fire before StartExecution is allowed (the same race as PR-023's).
  depends_on = [aws_iam_role_policy.scheduler]
}
