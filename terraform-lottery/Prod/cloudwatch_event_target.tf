resource "aws_cloudwatch_event_target" "trigger_state_machine" {
  rule      = aws_cloudwatch_event_rule.weekly_trigger.name
  target_id = "start-lottery-etl-pipeline"
  arn       = aws_sfn_state_machine.pipeline_state_machine.arn
  role_arn  = "arn:aws:iam::913524903233:role/eventbridge-to-sfn-role-prod" # PR-009: role moved to terraform/modules/iam (literal ARN, same value)
}
