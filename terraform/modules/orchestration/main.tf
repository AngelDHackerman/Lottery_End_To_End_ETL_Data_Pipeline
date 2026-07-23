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
#
# PR-022 (Gold): three things are added here.
#   1. The 7 CTAS files in sql/gold/ are uploaded to s3://<partitioned>/sql/gold/.
#   2. A single-file "gold-purge" Lambda drops each gold table + empties its S3 prefix,
#      then returns the CREATE statement (Athena runs one statement per call, and a CTAS
#      onto a non-empty location fails — see src/loteria/gold/purge_and_load.py).
#   3. A `BuildGold` Map state (one iteration per SQL file) runs purge -> CTAS.
# No gold crawler: Athena CTAS `CREATE TABLE` registers the gold_* tables (and their
# partitions) in the Glue catalog itself, so a crawler would be redundant. See the
# catalog module README for the reasoning behind skipping roadmap step 4.

locals {
  gold_sql_dir = "${path.module}/../../../sql/gold"
  # Baked at plan time: the Map iterates this static list, so the state machine never
  # has to list S3 at runtime. Each item feeds one purge -> CTAS iteration.
  gold_sql_keys = [
    for f in fileset(local.gold_sql_dir, "*.sql") : { sqlKey = "sql/gold/${f}" }
  ]
}

# Upload the CTAS SQL (authored in PR-021) to the partitioned bucket. The purge Lambda
# reads each file from here at run time.
resource "aws_s3_object" "gold_sql" {
  for_each = fileset(local.gold_sql_dir, "*.sql")

  bucket = var.partitioned_bucket_name
  key    = "sql/gold/${each.value}"
  source = "${local.gold_sql_dir}/${each.value}"
  etag   = filemd5("${local.gold_sql_dir}/${each.value}")
}

# The gold-purge Lambda ships as a single .py zipped by Terraform — it only needs boto3,
# which the Lambda runtime already provides, so it skips the extractor's build pipeline.
data "archive_file" "gold_purge" {
  type        = "zip"
  source_file = "${path.module}/../../../src/loteria/gold/purge_and_load.py"
  output_path = "${path.module}/build/gold_purge_and_load.zip"
}

resource "aws_lambda_function" "gold_purge" {
  function_name    = "lottery-gold-purge-${var.environment}"
  filename         = data.archive_file.gold_purge.output_path
  source_code_hash = data.archive_file.gold_purge.output_base64sha256
  handler          = "purge_and_load.handler"
  runtime          = "python3.12"
  timeout          = 120
  memory_size      = 256
  role             = var.gold_purge_lambda_role_arn

  tags = {
    Name        = "lottery-gold-purge-${var.environment}"
    Environment = var.environment
    Project     = "Lottery ETL"
    Owner       = "Angel Hackerman"
  }
}

resource "aws_sfn_state_machine" "pipeline_state_machine" {
  name     = "lottery-etl-pipeline-${var.environment}"
  role_arn = var.sfn_execution_role_arn

  definition = jsonencode({
    Comment = "Run ETL pipeline: extractor Lambda → transformer Glue → silver crawlers → gold CTAS",
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
        Next = "PrepGold"
      },

      # Inject the (plan-time) list of gold SQL keys into the state so the Map can
      # iterate it. Kept as a Pass state (rather than a JSONata literal) so the machine
      # stays in the default JSONPath language, consistent with the states above.
      PrepGold = {
        Type       = "Pass",
        Result     = { sqlKeys = local.gold_sql_keys },
        ResultPath = "$.gold",
        Next       = "BuildGold"
      },

      # One iteration per gold table: purge (drop table + empty S3 prefix, returns the
      # CREATE statement) -> run the CTAS. MaxConcurrency caps parallel Athena CTAS; the
      # 7 tables are independent (all read only silver_*), so parallelism is safe.
      BuildGold = {
        Type           = "Map",
        ItemsPath      = "$.gold.sqlKeys",
        MaxConcurrency = 3,
        Iterator = {
          StartAt = "PurgeAndLoad",
          States = {
            PurgeAndLoad = {
              Type     = "Task",
              Resource = "arn:aws:states:::lambda:invoke",
              Parameters = {
                FunctionName = aws_lambda_function.gold_purge.arn,
                Payload = {
                  "bucket"           = var.partitioned_bucket_name,
                  "sqlKey.$"         = "$.sqlKey",
                  "correlation_id.$" = "$$.Execution.Name"
                }
              },
              # Lift the Lambda's return out of the invoke envelope for the CTAS step.
              ResultSelector = {
                "queryString.$" = "$.Payload.queryString"
              },
              Next = "RunCTAS"
            },
            RunCTAS = {
              Type     = "Task",
              Resource = "arn:aws:states:::athena:startQueryExecution.sync",
              Parameters = {
                "QueryString.$" = "$.queryString",
                WorkGroup       = var.athena_workgroup_name,
                QueryExecutionContext = {
                  Database = var.database_name
                }
              },
              End = true
            }
          }
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
