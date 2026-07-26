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

# --- Gold layer (PR-022) ---
output "gold_purge_lambda_name" {
  description = "Name of the gold-purge Lambda (drop table + empty prefix before each CTAS)."
  value       = aws_lambda_function.gold_purge.function_name
}

output "gold_purge_lambda_arn" {
  description = "ARN of the gold-purge Lambda."
  value       = aws_lambda_function.gold_purge.arn
}

# --- PR-023: log groups (consumed by PR-024's dashboard / PR-025's alarms) ---
output "gold_purge_log_group_name" {
  description = "Name of the gold-purge Lambda's CloudWatch log group."
  value       = aws_cloudwatch_log_group.gold_purge.name
}

output "state_machine_log_group_name" {
  description = "Name of the Step Functions execution log group. Null when sfn_log_level = \"OFF\"."
  value       = one(aws_cloudwatch_log_group.state_machine[*].name)
}
