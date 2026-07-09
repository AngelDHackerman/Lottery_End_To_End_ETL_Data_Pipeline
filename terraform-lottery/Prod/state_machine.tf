resource "aws_sfn_state_machine" "pipeline_state_machine" {
  name     = "lottery-etl-pipeline-${var.environment}"
  role_arn = "arn:aws:iam::913524903233:role/sfn-lottery-execution-role-prod" # PR-009: role moved to terraform/modules/iam (literal ARN, same value)

  definition = jsonencode({
    Comment = "Run ETL pipeline: extractor Lambda → transformer Glue → Glue Crawler",
    StartAt = "RunExtractorLambda",
    States = {
      RunExtractorLambda = {
        Type     = "Task",
        Resource = "arn:aws:states:::lambda:invoke",
        Parameters = {
          FunctionName = "arn:aws:lambda:${var.aws_region}:${var.aws_account_id}:function:${var.extractor_lambda_name}",
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
          Name = var.glue_crawler_premios
        },
        Next = "RunSorteosCrawler"
      },

      RunSorteosCrawler = {
        Type     = "Task",
        Resource = "arn:aws:states:::aws-sdk:glue:startCrawler",
        Parameters = {
          Name = var.glue_crawler_sorteos
        },
        End = true
      }
    }
  })
}