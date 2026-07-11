# Module: observability
# SNS alerts topic + optional email subscription (PR-014). This is deliberately a
# placeholder foundation: Phase 4 (PR-024..PR-028) adds the CloudWatch dashboard,
# alarms, and custom metrics that publish to this topic.
#
# NEW resources — nothing existed in AWS to import.

resource "aws_sns_topic" "alerts" {
  name = "loteria-alerts-${var.environment}"
}

# Email subscription, only when an address is provided. NOTE: SNS email subscriptions
# require the recipient to click the confirmation link AWS sends — Terraform cannot
# confirm it (the subscription shows "pending confirmation" until then).
resource "aws_sns_topic_subscription" "email_alerts" {
  count = var.alert_email != "" ? 1 : 0

  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}
