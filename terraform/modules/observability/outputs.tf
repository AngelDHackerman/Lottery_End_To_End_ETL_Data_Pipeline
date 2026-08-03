# Outputs exposed by the "observability" module.
# Consumed by the Phase 4 alarms (PR-025) and the DQ-gate fail state (PR-033).

output "alerts_topic_arn" {
  description = "ARN of the alerts SNS topic."
  value       = aws_sns_topic.alerts.arn
}

# PR-024: handy for the README / a quick console link.
output "dashboard_name" {
  description = "Name of the pipeline CloudWatch dashboard."
  value       = aws_cloudwatch_dashboard.loteria_pipeline.dashboard_name
}

output "dashboard_url" {
  description = "Console URL for the pipeline dashboard."
  value       = "https://${var.aws_region}.console.aws.amazon.com/cloudwatch/home?region=${var.aws_region}#dashboards:name=${aws_cloudwatch_dashboard.loteria_pipeline.dashboard_name}"
}

# PR-025: names are what `aws cloudwatch describe-alarms --alarm-names ...` takes, which is
# how the runbook verifies each alarm's state after an apply.
output "alarm_names" {
  description = "Names of every metric alarm created by this module."
  value = [
    aws_cloudwatch_metric_alarm.sfn_execution_failed.alarm_name,
    aws_cloudwatch_metric_alarm.sfn_no_recent_success.alarm_name,
    aws_cloudwatch_metric_alarm.extractor_errors.alarm_name,
    aws_cloudwatch_metric_alarm.glue_transform_failed.alarm_name,
    aws_cloudwatch_metric_alarm.crawler_start_failed.alarm_name,
    aws_cloudwatch_metric_alarm.scrapedo_failed.alarm_name,
  ]
}

# Not a metric alarm — the crawler-failure signal is an EventBridge rule (see alarms.tf 5b),
# so it will not show up in `describe-alarms`.
output "crawler_failed_rule_name" {
  description = "Name of the EventBridge rule that notifies on a failed silver crawl."
  value       = aws_cloudwatch_event_rule.crawler_failed.name
}
