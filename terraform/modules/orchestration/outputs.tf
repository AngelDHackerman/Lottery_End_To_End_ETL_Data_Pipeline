# Outputs exposed by the "orchestration" module.

output "state_machine_arn" {
  description = "ARN of the ETL pipeline state machine."
  value       = aws_sfn_state_machine.pipeline_state_machine.arn
}

output "state_machine_name" {
  description = "Name of the ETL pipeline state machine."
  value       = aws_sfn_state_machine.pipeline_state_machine.name
}

output "weekly_rule_name" {
  description = "Name of the weekly EventBridge trigger rule."
  value       = aws_cloudwatch_event_rule.weekly_etl_trigger.name
}
