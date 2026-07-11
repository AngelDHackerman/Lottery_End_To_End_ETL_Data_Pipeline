# Outputs exposed by the "observability" module.
# Consumed by the Phase 4 alarms (PR-025) and the DQ-gate fail state (PR-033).

output "alerts_topic_arn" {
  description = "ARN of the alerts SNS topic."
  value       = aws_sns_topic.alerts.arn
}
