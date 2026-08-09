# PR-025: the alarm set. Every alarm notifies the SNS topic from PR-014.
#
# Design premise: the state machine has NO Retry and NO Catch (see the orchestration
# module), so any failing stage fails the whole execution. `SFN_ExecutionFailed` is
# therefore the one alarm that detects *everything*; the per-stage alarms below exist for
# ATTRIBUTION — they answer "which stage broke?" in the notification itself instead of
# making someone open the console. Expect 2–3 emails from a single bad run, by design.
#
# ⚠️ Two of the roadmap's six alarms could not be built as written. Both are documented at
# their resource; short version:
#   - Alarms 4 & 5 asked for `AWS/Glue` `Job.failure` / `glue.driver.aggregate.numFailedTasks`.
#     Those metrics DO NOT EXIST for a Python Shell job or for crawlers (PR-024 verified the
#     whole namespace holds one account-level gauge). Replaced with `AWS/States`
#     service-integration metrics, plus an EventBridge rule for the crawler case.
#   - Alarm 2 asked for an 8-day window. CloudWatch caps an alarm's total evaluation period
#     at SEVEN days. 7 is what the API allows and, as it happens, the right number here.
#
# No SNS topic policy is needed for these: CloudWatch publishes to a same-account topic
# under the topic's default policy. The EventBridge rule at the bottom is the exception —
# it needs an explicit grant, and adding one replaces that default policy.

locals {
  alarm_prefix = "loteria"

  # Every alarm points here. Kept as a list so adding a second action later is a one-line
  # change rather than an edit in six places.
  alarm_actions = [aws_sns_topic.alerts.arn]
}

# ---------------------------------------------------------------------------------------
# 1. The pipeline failed.
# ---------------------------------------------------------------------------------------
# `treat_missing_data = "notBreaching"` is load-bearing: the pipeline runs once a week, so
# for ~99.9% of 5-minute periods this metric has no datapoints. The default ("missing")
# would park the alarm in INSUFFICIENT_DATA forever and make its state meaningless.
#
# Consequence worth knowing before the first page: with a 5-minute period, the alarm
# auto-returns to OK five minutes after the failure. It is a PULSE, not a sticky state —
# the notification is the signal; the console will read OK by the time you look. That is
# also why `ok_actions` is deliberately unset (see the note above alarm 2).
resource "aws_cloudwatch_metric_alarm" "sfn_execution_failed" {
  alarm_name        = "${local.alarm_prefix}-sfn-execution-failed-${var.environment}"
  alarm_description = "The ETL state machine failed an execution. Because the machine has no Retry/Catch, this fires for a failure in ANY stage — check the per-stage alarms (glue-transform-failed / crawler-*) and the dashboard for attribution."

  namespace   = "AWS/States"
  metric_name = "ExecutionsFailed"
  dimensions  = { StateMachineArn = var.state_machine_arn }

  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = local.alarm_actions
}

# ---------------------------------------------------------------------------------------
# 2. The pipeline stopped running at all (dead man's switch).
# ---------------------------------------------------------------------------------------
# The failure modes alarm 1 cannot see: the EventBridge rule is disabled or deleted, its
# IAM role loses StartExecution, the schedule expression is wrong. Nothing fails — nothing
# *happens* — and a silent pipeline looks identical to a healthy idle one.
#
# ⚠️ THE ROADMAP ASKED FOR 8 DAYS. CLOUDWATCH WILL NOT ACCEPT IT. From the PutMetricAlarm
# reference: "An alarm's total current evaluation period can be no longer than seven days,
# so Period multiplied by EvaluationPeriods can't be more than 604,800 seconds." 8 × 86,400
# = 691,200 > 604,800 — the API rejects it, so no amount of composite/expression cleverness
# in a single metric alarm gets to 8. 7 days × 86,400 s = 604,800 s is the exact maximum.
#
# 7 days is the better number anyway. The trigger is weekly (Thursday 18:00 UTC), so in any
# 7 consecutive UTC-day buckets a healthy pipeline has exactly one success — never all-7
# breaching, no false positive. A MISSED Thursday leaves 7 empty buckets and the alarm
# fires at the next midnight UTC, ~6 h after the run should have happened. The 8-day target
# would have added a day of silence for nothing.
#
# `treat_missing_data = "breaching"` is what makes this work at all, and it is the opposite
# of alarm 1's setting: `ExecutionsSucceeded` publishes NO datapoint on a day with no run
# (it does not publish a zero). Under the default "missing" this alarm could never fire —
# the exact scenario it exists to catch would produce no data to evaluate.
#
# `ok_actions` is unset here too: this alarm sits in ALARM until a run succeeds, and the
# recovery email would arrive at the same time as everything else about a successful run.
resource "aws_cloudwatch_metric_alarm" "sfn_no_recent_success" {
  alarm_name        = "${local.alarm_prefix}-sfn-no-success-${var.no_success_alarm_days}d-${var.environment}"
  alarm_description = "No successful ETL execution in ${var.no_success_alarm_days} days. The weekly EventBridge trigger is not firing, or every run since has failed. Check the rule '${var.weekly_rule_name}' is ENABLED and its IAM role can still StartExecution."

  namespace   = "AWS/States"
  metric_name = "ExecutionsSucceeded"
  dimensions  = { StateMachineArn = var.state_machine_arn }

  statistic = "Sum"
  period    = 86400
  # All N daily buckets must be empty/zero. datapoints_to_alarm == evaluation_periods makes
  # that explicit rather than relying on the consecutive-datapoints default.
  evaluation_periods  = var.no_success_alarm_days
  datapoints_to_alarm = var.no_success_alarm_days
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"

  alarm_actions = local.alarm_actions
}

# ---------------------------------------------------------------------------------------
# 3. The extractor Lambda errored.
# ---------------------------------------------------------------------------------------
# Scoped to the extractor only, per the roadmap. The gold-purge Lambda is deliberately not
# alarmed: it runs 7× inside the Map state, and any failure there fails the execution, so
# alarm 1 already covers it — a second alarm would only duplicate the email.
resource "aws_cloudwatch_metric_alarm" "extractor_errors" {
  alarm_name        = "${local.alarm_prefix}-extractor-errors-${var.environment}"
  alarm_description = "The extractor Lambda (${var.extractor_lambda_name}) reported an error. Most likely: the scrape failed (see the scrapedo-failed alarm and the Cloudflare waiting-room caveat in PR-026's runbook), the site's layout changed, or Secrets Manager/S3 access broke."

  namespace   = "AWS/Lambda"
  metric_name = "Errors"
  dimensions  = { FunctionName = var.extractor_lambda_name }

  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = local.alarm_actions
}

# ---------------------------------------------------------------------------------------
# 4. The Glue transform job failed. (roadmap "Glue_JobFailed")
# ---------------------------------------------------------------------------------------
# The roadmap's `AWS/Glue` `Job.failure` does not exist — see the header note and PR-024.
#
# This substitute is EXACT rather than approximate, because the state machine invokes the
# job with `glue:startJobRun.sync`: the integration stays open until the job run reaches a
# terminal state, so "integration failed" means "the job run failed", not merely "we could
# not start it". Contrast the crawlers below, where that equivalence does NOT hold.
#
# `local.integration_arn` (dashboard.tf) carries the account-qualified dimension value —
# the bare `arn:aws:states:::glue:...` form silently matches nothing.
resource "aws_cloudwatch_metric_alarm" "glue_transform_failed" {
  alarm_name        = "${local.alarm_prefix}-glue-transform-failed-${var.environment}"
  alarm_description = "The bronze→silver Glue transform failed (SFN service integration glue:startJobRun.sync). Glue publishes no per-job metrics for Python Shell jobs, so the detail is in the log widgets on dashboard '${aws_cloudwatch_dashboard.loteria_pipeline.dashboard_name}' / log group ${var.glue_error_log_group_name}."

  namespace   = "AWS/States"
  metric_name = "ServiceIntegrationsFailed"
  dimensions  = { ServiceIntegrationResourceArn = local.integration_arn.glue_job }

  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = local.alarm_actions
}

# ---------------------------------------------------------------------------------------
# 5a. A crawler could not be STARTED. (roadmap "Crawler_Failed", part 1 of 2)
# ---------------------------------------------------------------------------------------
# Catches CrawlerRunningException, a deleted crawler, a revoked glue:StartCrawler grant.
#
# ⚠️ It does NOT catch a crawl that starts and then fails. The state machine uses
# `aws-sdk:glue:startCrawler`, which is fire-and-forget — there is no `.sync` variant — so
# the integration succeeds the instant the crawler accepts the start call, whatever happens
# afterwards. That gap is why 5b exists.
#
# The dimension identifies the integration TYPE, so this covers both silver crawlers as one
# series; 5b's notification carries the crawler name.
resource "aws_cloudwatch_metric_alarm" "crawler_start_failed" {
  alarm_name        = "${local.alarm_prefix}-crawler-start-failed-${var.environment}"
  alarm_description = "A silver crawler could not be started (SFN service integration aws-sdk:glue:startCrawler). Covers both crawlers as one series. A crawl that starts and then FAILS is a different signal — see the EventBridge rule ${local.alarm_prefix}-crawler-failed-${var.environment}."

  namespace   = "AWS/States"
  metric_name = "ServiceIntegrationsFailed"
  dimensions  = { ServiceIntegrationResourceArn = local.integration_arn.crawler }

  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = local.alarm_actions
}

# ---------------------------------------------------------------------------------------
# 5b. A crawl started and then FAILED. (roadmap "Crawler_Failed", part 2 of 2)
# ---------------------------------------------------------------------------------------
# Today this is completely silent: the crawler is fire-and-forget (5a), Glue publishes no
# crawler metrics at all (PR-024), and the execution goes on to build gold regardless. A
# failed crawl means silver's new partitions are never registered and the gold CTAS reads a
# stale catalog — wrong numbers, green pipeline. Worth closing.
#
# Not a metric alarm, on purpose. The two candidates were:
#   - a Logs metric filter over /aws-glue/crawlers — REJECTED. That group is ACCOUNT-WIDE
#     (PR-023 §3) and another project already writes to it (stream
#     `near-real-time-crypto-silver-crawler-crypto`, verified live). Metric filters apply to
#     every stream in a group with no way to scope by stream, and the crawler name does not
#     appear on individual ERROR lines — only in the stream name and the opening BENCHMARK
#     line. So the filter would alarm on an unrelated project's crawler.
#   - this EventBridge rule — exact, scoped by `crawlerName`, and the event body carries the
#     failure message straight into the email.
#
# States are `Started` / `Succeeded` / `Failed`, capitalized (Glue dev guide).
resource "aws_cloudwatch_event_rule" "crawler_failed" {
  name        = "${local.alarm_prefix}-crawler-failed-${var.environment}"
  description = "Notify the alerts topic when a silver crawler run ends in Failed. Covers the gap left by the fire-and-forget aws-sdk:glue:startCrawler integration."

  event_pattern = jsonencode({
    source        = ["aws.glue"]
    "detail-type" = ["Glue Crawler State Change"]
    detail = {
      state       = ["Failed"]
      crawlerName = [var.premios_crawler_name, var.sorteos_crawler_name]
    }
  })
}

resource "aws_cloudwatch_event_target" "crawler_failed_to_sns" {
  rule      = aws_cloudwatch_event_rule.crawler_failed.name
  target_id = "alerts-topic"
  arn       = aws_sns_topic.alerts.arn

  # The raw event is a wall of JSON in an email. Pull out the three fields that matter.
  input_transformer {
    input_paths = {
      crawler = "$.detail.crawlerName"
      message = "$.detail.message"
      time    = "$.time"
    }
    input_template = "\"Glue crawler <crawler> FAILED at <time>: <message>\""
  }
}

# ⚠️ THIS REPLACES THE TOPIC'S DEFAULT POLICY. EventBridge cannot publish to SNS without an
# explicit resource-policy grant, and attaching aws_sns_topic_policy overwrites whatever
# SNS created at topic-creation time. The first statement below is a faithful reproduction
# of that default (account-scoped via AWS:SourceOwner) — dropping it would silently break
# the console, the CLI, and subscription management on this topic.
data "aws_iam_policy_document" "alerts_topic" {
  statement {
    sid    = "DefaultStatement"
    effect = "Allow"

    principals {
      type        = "AWS"
      identifiers = ["*"]
    }

    actions = [
      "SNS:GetTopicAttributes",
      "SNS:SetTopicAttributes",
      "SNS:AddPermission",
      "SNS:RemovePermission",
      "SNS:DeleteTopic",
      "SNS:Subscribe",
      "SNS:ListSubscriptionsByTopic",
      "SNS:Publish",
    ]

    resources = [aws_sns_topic.alerts.arn]

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceOwner"
      values   = [local.account_id]
    }
  }

  statement {
    sid    = "AllowEventBridgePublish"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }

    actions   = ["SNS:Publish"]
    resources = [aws_sns_topic.alerts.arn]

    # Scope to this rule specifically, so the grant does not extend to every EventBridge
    # rule in the account.
    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_cloudwatch_event_rule.crawler_failed.arn]
    }
  }
}

resource "aws_sns_topic_policy" "alerts" {
  arn    = aws_sns_topic.alerts.arn
  policy = data.aws_iam_policy_document.alerts_topic.json
}

# ---------------------------------------------------------------------------------------
# 6. scrape.do returned a non-200. (roadmap "ScrapeDo_Failed")
# ---------------------------------------------------------------------------------------
# Watches PR-026's DIMENSIONLESS `ScraperHttpErrors`, not `ScraperHttpStatus{StatusCode}`.
# That split exists precisely for this alarm: an alarm evaluates ONE time series with ONE
# dimension set, so alarming on "any non-200" via the dimensioned metric would mean
# enumerating every code in advance — and the code that eventually matters would be the one
# not on the list. `ScraperHttpErrors` is emitted once per non-200 with no dimensions, so
# the threshold is a plain >= 1.
#
# Value over alarm 3: the extractor raises on a non-200, so a proxy problem ALREADY fires
# Lambda_Errors and SFN_ExecutionFailed — but as a generic "Lambda error", indistinguishable
# from a parser bug. This one names the cause: scrape.do is on the FREE tier, and 401/402/429
# means "start paying / swap proxy", which is an action, not an investigation.
#
# ⚠️ It does NOT catch the Cloudflare waiting room, which is the failure that actually hit
# on 2026-07-19/20: that returns HTTP **200** with a queue page. Content inspection is
# PR-031's job. A green scraper alarm is not proof the scrape returned real data.
#
# `namespace` must equal loteria.common.metrics.NAMESPACE. A mismatch fails silently in
# both directions — the publish is IAM-denied and swallowed, and this alarm sits in
# INSUFFICIENT_DATA looking like good news.
resource "aws_cloudwatch_metric_alarm" "scrapedo_failed" {
  alarm_name        = "${local.alarm_prefix}-scrapedo-failed-${var.environment}"
  alarm_description = "scrape.do returned a non-200 for the weekly scrape. Check the status-code breakdown on dashboard '${aws_cloudwatch_dashboard.loteria_pipeline.dashboard_name}': 401 = token/auth, 402 = free-tier quota exhausted, 429 = rate limited, 5xx = proxy-side. Does NOT cover the Cloudflare waiting room (that returns 200)."

  namespace   = var.metrics_namespace
  metric_name = "ScraperHttpErrors"

  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = local.alarm_actions
}
