# What the nightly pipeline says when nothing fails (UY-045). pipeline.tf's alarm covers a night
# that FAILED; these four cover the nights that succeed, or never start, and still need a person:
#
#   lottery-uy-open-draw-gaps     a draw that should have happened did not, and no
#                                 calendar_events row explains it (draw_gaps, D13-D15)
#   lottery-uy-silver-quarantine  the parser set rows aside; draw_gaps was not rewritten
#   lottery-uy-fetch-errors       the canary: the site answered the nightly run with errors
#   lottery-uy-pipeline-no-success  the dead-man: no successful execution in two days
#
# The first three read numbers the Lambdas publish every real night as one log line in the
# Embedded Metric Format (src/sorteos/core/metrics.py): no PutMetricData, so no IAM change. The
# canary makes no request of its own (owner, UY-045 1a): it counts what the nightly fetch
# already asked.
#
# They are STATE alarms (owner, UY-045 2a): one e-mail when the count leaves 0, then ALARM
# until a night publishes 0 again, so the console says what is true today. Master's PR-025
# lesson decides the numbers: the count arrives once a night, so an alarm over one short period
# would be back in OK an hour later. Each alarm therefore looks at the last 26 hourly periods
# and needs one of them at 1 or more: every night's datapoint is still in view when the next
# one arrives (24 h later), and a clean night clears the alarm about two hours after it. Hours
# without a datapoint are not breaching: a night that did not run publishes nothing, and that
# is the dead-man's job, not theirs.
#
# No ok_actions (PR-025): the recovery would mail a second time for the same event.
#
# The topic is Santa Lucía's, read in pipeline.tf (data.aws_sns_topic.alerts), never managed.

locals {
  metrics_namespace   = "Loteria/UY" # sorteos.core.metrics.NAMESPACE
  metrics_dimensions  = { Environment = var.environment }
  nightly_alarm_hours = 26
  # What an e-mail's reader needs first: where the night's reports are.
  alarm_where = "Reports: the last execution of ${local.state_machine_name} (Step Functions), output $.fetch.report and $.silver.report. Runbook: docs/runbooks/UY-045-alarmas.md."

  nightly_count_alarms = {
    open-draw-gaps = {
      metric      = "OpenDrawGaps"
      description = "A UY draw that should have happened is missing and no calendar_events row explains it. Query: SELECT * FROM ${var.database_name}.silver_draw_gaps WHERE status = 'open' (workgroup ${aws_athena_workgroup.uy.name}). If the draw was suspended or moved, add the row to src/sorteos/uy/reference/calendar_events.csv with its source; if the site published it late, the next night closes it. ${local.alarm_where}"
    }
    silver-quarantine = {
      metric      = "SilverQuarantineRows"
      description = "UY silver has rows in quarantine: the parser could not read a page it had read as a draw, most likely because the site changed its layout. The execution SUCCEEDED, but draw_gaps was not rewritten and the missing-draw alarm is blind until this is fixed. Query: SELECT * FROM ${var.database_name}.silver_quarantine. ${local.alarm_where}"
    }
    fetch-errors = {
      metric      = "FetchErrors"
      description = "The canary: last night's UY fetch left keys in 'error' (the count is in $.fetch.report.by_state). One key is usually one PDF the site refuses (it becomes 'missing' after 3 identical failures); many keys mean the site is blocking or changed. The execution SUCCEEDED and nothing was lost: every key in 'error' is asked again the next night. ${local.alarm_where}"
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "nightly_count" {
  for_each = local.nightly_count_alarms

  alarm_name        = "lottery-uy-${each.key}-${var.environment}"
  alarm_description = each.value.description

  namespace   = local.metrics_namespace
  metric_name = each.value.metric
  dimensions  = local.metrics_dimensions

  statistic           = "Maximum"
  period              = 3600
  evaluation_periods  = local.nightly_alarm_hours
  datapoints_to_alarm = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = [data.aws_sns_topic.alerts.arn]
}

# --- The dead-man (owner, UY-045 3a) -----------------------------------------------------------
#
# `ExecutionsSucceeded` publishes NOTHING on a day with no run (master's PR-025), so missing
# data is breaching here, the opposite of the alarms above. Two daily buckets, both without a
# success: a daily bucket's edge can fall next to the run (02:30 UTC), so one bucket alone could
# be empty on a normal night, and two cannot. A night that fails already mails through
# pipeline.tf's alarm; this one is for the schedule that stopped firing, or for every run
# failing. A manual dry run counts as a success: the machine runs, which is what this asks.

resource "aws_cloudwatch_metric_alarm" "pipeline_no_success" {
  alarm_name        = "${local.state_machine_name}-no-success-${var.no_success_alarm_days}d"
  alarm_description = "No successful execution of ${local.state_machine_name} in ${var.no_success_alarm_days} days. Either the schedule ${aws_scheduler_schedule.nightly.name} is not firing (is it ENABLED? can its role still StartExecution?) or every run since has failed. The next successful night catches up on its own: the fetch window starts after the last day the manifest holds."

  namespace   = "AWS/States"
  metric_name = "ExecutionsSucceeded"
  dimensions  = { StateMachineArn = aws_sfn_state_machine.pipeline.arn }

  statistic           = "Sum"
  period              = 86400
  evaluation_periods  = var.no_success_alarm_days
  datapoints_to_alarm = var.no_success_alarm_days
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"

  alarm_actions = [data.aws_sns_topic.alerts.arn]
}
