# Module: orchestration
# Step Functions state machine + the SINGLE weekly EventBridge trigger.
# Migrated from terraform-lottery/Prod/{state_machine.tf, eventbridge.tf} in PR-012 via
# cross-state `terraform state rm` (legacy) + `terraform import` (here) — neither is
# recreated. See docs/runbooks/PR-012-catalog-orchestration-migration.md.
#
# PR-012 also KILLS the duplicate trigger (see README): the legacy stack had two rules
# firing the same state machine — `weekly_etl_trigger` (Mon 18:00 UTC, kept, moved here)
# and `weekly_trigger` (Sat 14:00 UTC, DESTROYED via the legacy stack).
#
# The crawler names come from the catalog module's outputs (not var strings), so the
# Step Function always references real, managed resources.

resource "aws_sfn_state_machine" "pipeline_state_machine" {
  name     = "lottery-etl-pipeline-${var.environment}"
  role_arn = var.sfn_execution_role_arn

  definition = jsonencode({
    Comment = "Run ETL pipeline: extractor Lambda → transformer Glue → Glue Crawler",
    StartAt = "RunExtractorLambda",
    States = {
      RunExtractorLambda = {
        Type     = "Task",
        Resource = "arn:aws:states:::lambda:invoke",
        Parameters = {
          FunctionName = var.extractor_lambda_arn,
          Payload      = {}
        },
        Next = "RunTransformerGlueJob"
      },

      RunTransformerGlueJob = {
        Type     = "Task",
        Resource = "arn:aws:states:::glue:startJobRun.sync",
        Parameters = {
          JobName = var.glue_job_name
        },
        Next = "RunPremiosCrawler"
      },

      RunPremiosCrawler = {
        Type     = "Task",
        Resource = "arn:aws:states:::aws-sdk:glue:startCrawler",
        Parameters = {
          Name = var.premios_crawler_name
        },
        Next = "RunSorteosCrawler"
      },

      RunSorteosCrawler = {
        Type     = "Task",
        Resource = "arn:aws:states:::aws-sdk:glue:startCrawler",
        Parameters = {
          Name = var.sorteos_crawler_name
        },
        End = true
      }
    }
  })
}

# The one weekly trigger: every Monday 18:00 UTC (12:00 Guatemala).
resource "aws_cloudwatch_event_rule" "weekly_etl_trigger" {
  name                = "lottery-etl-weekly-trigger-${var.environment}"
  schedule_expression = "cron(0 18 ? * MON *)"
  description         = "Trigger the lottery ETL Step Function every Monday at 12:00 PM GMT-6"
}

resource "aws_cloudwatch_event_target" "trigger_step_function" {
  rule      = aws_cloudwatch_event_rule.weekly_etl_trigger.name
  target_id = "StepFunctionLotteryETL"
  arn       = aws_sfn_state_machine.pipeline_state_machine.arn
  role_arn  = var.eventbridge_to_sfn_role_arn
}
