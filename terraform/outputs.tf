# Root outputs for the main stack.

output "alerts_topic_arn" {
  description = "ARN of the alerts SNS topic (publish here from alarms / the DQ gate)."
  value       = module.observability.alerts_topic_arn
}

output "state_machine_arn" {
  description = "ARN of the ETL pipeline state machine."
  value       = module.orchestration.state_machine_arn
}

# PR-024: surfaced at the root so `terraform output dashboard_url` works. The observability
# module declared these, but a module output is not a root output — without these two
# stanzas the values exist only inside the module and `terraform output` cannot see them.
output "dashboard_name" {
  description = "Name of the pipeline CloudWatch dashboard."
  value       = module.observability.dashboard_name
}

output "dashboard_url" {
  description = "Console URL for the pipeline CloudWatch dashboard."
  value       = module.observability.dashboard_url
}
