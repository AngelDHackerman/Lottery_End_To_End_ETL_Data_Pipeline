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
