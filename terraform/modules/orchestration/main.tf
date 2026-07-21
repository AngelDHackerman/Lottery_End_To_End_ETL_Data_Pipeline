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
          # PR-018: pass the execution name as CORRELATION_ID so every Lambda + Glue log
          # line in this run shares one id. The Lambda handler reads it from the payload.
          Payload = {
            "CORRELATION_ID.$" = "$$.Execution.Name"
          }
        },
        Next = "RunTransformerGlueJob"
      },

      RunTransformerGlueJob = {
        Type     = "Task",
        Resource = "arn:aws:states:::glue:startJobRun.sync",
        Parameters = {
          JobName = var.glue_job_name,
          # PR-018: same correlation id, delivered as a Glue job argument. The zipapp
          # entry point (scripts/glue_zip_main.py) bridges --CORRELATION_ID into the
          # environment, where configure_logging() reads it.
          Arguments = {
            "--CORRELATION_ID.$" = "$$.Execution.Name"
          }
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

# The one weekly trigger: every Thursday 18:00 UTC (12:00 Guatemala).
#
# Moved off Monday: the Saturday draws (especially high-stakes ones like the
# extraordinario) drive a surge of traffic that keeps loteria.org.gt behind a Cloudflare
# Waiting Room for days afterward. A Monday scrape lands squarely in that window and comes
# back with the queue page instead of the results (the proxy still returns HTTP 200, so
# the extractor fails at the sorteo-link selector). Thursday is the calm point of the
# week — well after the post-draw surge and before the next Saturday's — so the scrape is
# far likelier to reach the real page. The site still shows only the latest sorteo on
# Thursday, so no data is skipped; it is read at a quieter time. This lowers the odds of a
# Cloudflare hit but does not remove the single-run-per-week SPOF — see PR-026/PR-031 for
# retry/detection follow-ups.
resource "aws_cloudwatch_event_rule" "weekly_etl_trigger" {
  name                = "lottery-etl-weekly-trigger-${var.environment}"
  schedule_expression = "cron(0 18 ? * THU *)"
  description         = "Trigger the lottery ETL Step Function every Thursday at 12:00 PM GMT-6"
}

resource "aws_cloudwatch_event_target" "trigger_step_function" {
  rule      = aws_cloudwatch_event_rule.weekly_etl_trigger.name
  target_id = "StepFunctionLotteryETL"
  arn       = aws_sfn_state_machine.pipeline_state_machine.arn
  role_arn  = var.eventbridge_to_sfn_role_arn
}
