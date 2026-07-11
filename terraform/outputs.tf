# Root outputs for the main stack.

output "alerts_topic_arn" {
  description = "ARN of the alerts SNS topic (publish here from alarms / the DQ gate)."
  value       = module.observability.alerts_topic_arn
}

output "state_machine_arn" {
  description = "ARN of the ETL pipeline state machine."
  value       = module.orchestration.state_machine_arn
}
