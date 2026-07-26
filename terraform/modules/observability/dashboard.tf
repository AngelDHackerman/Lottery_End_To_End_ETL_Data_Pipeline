# PR-024: the pipeline dashboard.
#
# ⚠️ THE ROADMAP'S GLUE WIDGETS DO NOT EXIST. PR-024 asked for
# `glue.driver.aggregate.numCompletedTasks` and `glue.ALL.s3.filesystem.read_bytes`. Those
# are **Spark** job metrics; the transform is a Python Shell job, which publishes no job
# telemetry at all. Verified read-only against the live account: the entire `AWS/Glue`
# namespace holds exactly ONE metric, `ResourceUsage`, dimensioned
# (Type=Resource, Resource=Job|JobRun|InteractiveSession, Service=Glue, Class=None) — an
# account-level service-quota gauge with no `JobName` dimension. There are no crawler
# metrics whatsoever. Same pythonshell-vs-glueetl split as the PR-020 spike.
#
# What replaces them: Step Functions **service-integration** metrics. Every pipeline stage
# is an SFN integration, so `AWS/States` exposes per-stage success/failure/duration under
# the `ServiceIntegrationResourceArn` dimension. That covers the Glue job, the crawlers and
# the Athena CTAS with real numbers.
#
# ⚠️ Two traps in that dimension, both verified live:
#   1. Its value is ACCOUNT-QUALIFIED — `arn:aws:states:us-east-1:<acct>:glue:startJobRun.sync`
#      — NOT the bare `arn:aws:states:::glue:startJobRun.sync` the state machine definition
#      uses. Querying the bare form silently returns zero datapoints.
#   2. It identifies the integration TYPE, not the resource. `lambda:invoke` therefore
#      aggregates the extractor AND all 7 gold-purge calls; per-function detail comes from
#      the AWS/Lambda widgets below.
#
# S3 object counts per medallion layer are deliberately absent — that needs a custom metric
# emitter, which the roadmap scopes to the optional PR-027.

data "aws_caller_identity" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id

  # See trap (1) above: account-qualified, one per integration TYPE.
  integration_arn = {
    lambda   = "arn:aws:states:${var.aws_region}:${local.account_id}:lambda:invoke"
    glue_job = "arn:aws:states:${var.aws_region}:${local.account_id}:glue:startJobRun.sync"
    crawler  = "arn:aws:states:${var.aws_region}:${local.account_id}:aws-sdk:glue:startCrawler"
    athena   = "arn:aws:states:${var.aws_region}:${local.account_id}:athena:startQueryExecution.sync"
  }

  ok   = "#2ca02c"
  bad  = "#d62728"
  warn = "#ff7f0e"
  info = "#1f77b4"
  alt  = "#9467bd"
  mute = "#7f7f7f"
}

resource "aws_cloudwatch_dashboard" "loteria_pipeline" {
  dashboard_name = "loteria-pipeline-${var.environment}"

  dashboard_body = jsonencode({
    # The pipeline runs ONCE A WEEK, so the console's default 3-hour window would show an
    # empty dashboard almost always. 28 days ≈ 4 runs. periodOverride=auto lets each
    # widget keep its own period rather than being flattened to the window's.
    start          = "-P28D"
    periodOverride = "auto"

    widgets = [
      {
        type = "text", x = 0, y = 0, width = 24, height = 3,
        properties = {
          markdown = trimspace(<<-EOT
            # Lotería Santa Lucía — ETL pipeline
            **Cadence:** one run every Thursday 18:00 UTC (12:00 Guatemala) — see the orchestration module for why Thursday.
            **Flow:** extractor Lambda → transform Glue job (bronze→silver) → 2 silver crawlers → 7 gold CTAS (Athena).
            **Default window is 28 days (~4 runs).** Gaps between runs are expected, not outages.
            *Glue publishes no per-job metrics for Python Shell jobs, so Glue/crawler health is read from the Step Functions per-stage widgets and the log widgets at the bottom.*
          EOT
          )
        }
      },

      # --- Row 1: pipeline-level health -------------------------------------------------
      {
        type = "metric", x = 0, y = 3, width = 8, height = 6,
        properties = {
          title  = "Pipeline runs (daily)",
          view   = "timeSeries", stacked = true, region = var.aws_region,
          period = 86400,
          yAxis  = { left = { min = 0, showUnits = false } },
          metrics = [
            ["AWS/States", "ExecutionsSucceeded", "StateMachineArn", var.state_machine_arn, { stat = "Sum", label = "Succeeded", color = local.ok }],
            ["AWS/States", "ExecutionsFailed", "StateMachineArn", var.state_machine_arn, { stat = "Sum", label = "Failed", color = local.bad }],
            ["AWS/States", "ExecutionsAborted", "StateMachineArn", var.state_machine_arn, { stat = "Sum", label = "Aborted", color = local.warn }],
            ["AWS/States", "ExecutionsTimedOut", "StateMachineArn", var.state_machine_arn, { stat = "Sum", label = "Timed out", color = local.alt }],
          ]
        }
      },
      {
        type = "metric", x = 8, y = 3, width = 8, height = 6,
        properties = {
          title = "Execution duration",
          view  = "timeSeries", region = var.aws_region, period = 86400,
          yAxis = { left = { min = 0, label = "ms", showUnits = false } },
          metrics = [
            ["AWS/States", "ExecutionTime", "StateMachineArn", var.state_machine_arn, { stat = "p50", label = "p50", color = local.info }],
            ["AWS/States", "ExecutionTime", "StateMachineArn", var.state_machine_arn, { stat = "p90", label = "p90", color = local.warn }],
            ["AWS/States", "ExecutionTime", "StateMachineArn", var.state_machine_arn, { stat = "p99", label = "p99", color = local.bad }],
            ["AWS/States", "ExecutionTime", "StateMachineArn", var.state_machine_arn, { stat = "Maximum", label = "max", color = local.mute }],
          ]
        }
      },
      {
        type = "metric", x = 16, y = 3, width = 8, height = 6,
        properties = {
          title     = "Last 28 days",
          view      = "singleValue", region = var.aws_region, period = 2419200,
          sparkline = true,
          metrics = [
            ["AWS/States", "ExecutionsSucceeded", "StateMachineArn", var.state_machine_arn, { stat = "Sum", label = "Succeeded", color = local.ok }],
            ["AWS/States", "ExecutionsFailed", "StateMachineArn", var.state_machine_arn, { stat = "Sum", label = "Failed", color = local.bad }],
            ["AWS/States", "ExecutionTime", "StateMachineArn", var.state_machine_arn, { stat = "Average", label = "Avg duration", color = local.info }],
          ]
        }
      },

      # --- Row 2: per-stage, via SFN service integrations -------------------------------
      {
        type = "metric", x = 0, y = 9, width = 12, height = 6,
        properties = {
          title = "Per-stage failures (SFN service integrations)",
          view  = "timeSeries", stacked = true, region = var.aws_region, period = 86400,
          yAxis = { left = { min = 0, showUnits = false } },
          metrics = [
            ["AWS/States", "ServiceIntegrationsFailed", "ServiceIntegrationResourceArn", local.integration_arn.lambda, { stat = "Sum", label = "Lambda invoke (extractor + gold purge)", color = local.bad }],
            ["AWS/States", "ServiceIntegrationsFailed", "ServiceIntegrationResourceArn", local.integration_arn.glue_job, { stat = "Sum", label = "Glue transform job", color = local.warn }],
            ["AWS/States", "ServiceIntegrationsFailed", "ServiceIntegrationResourceArn", local.integration_arn.crawler, { stat = "Sum", label = "Silver crawlers", color = local.alt }],
            ["AWS/States", "ServiceIntegrationsFailed", "ServiceIntegrationResourceArn", local.integration_arn.athena, { stat = "Sum", label = "Gold CTAS (Athena)", color = local.info }],
          ]
        }
      },
      {
        type = "metric", x = 12, y = 9, width = 12, height = 6,
        properties = {
          title = "Per-stage duration (avg per call)",
          view  = "timeSeries", region = var.aws_region, period = 86400,
          yAxis = { left = { min = 0, label = "ms", showUnits = false } },
          metrics = [
            ["AWS/States", "ServiceIntegrationRunTime", "ServiceIntegrationResourceArn", local.integration_arn.glue_job, { stat = "Average", label = "Glue transform job", color = local.warn }],
            ["AWS/States", "ServiceIntegrationRunTime", "ServiceIntegrationResourceArn", local.integration_arn.athena, { stat = "Average", label = "Gold CTAS (per query)", color = local.info }],
            ["AWS/States", "ServiceIntegrationRunTime", "ServiceIntegrationResourceArn", local.integration_arn.crawler, { stat = "Average", label = "Silver crawlers", color = local.alt }],
            ["AWS/States", "ServiceIntegrationRunTime", "ServiceIntegrationResourceArn", local.integration_arn.lambda, { stat = "Average", label = "Lambda invoke", color = local.ok }],
          ]
        }
      },

      # --- Row 3: the two Lambdas ------------------------------------------------------
      {
        type = "metric", x = 0, y = 15, width = 8, height = 6,
        properties = {
          title = "Extractor Lambda — outcomes",
          view  = "timeSeries", region = var.aws_region, period = 86400,
          yAxis = { left = { min = 0, showUnits = false } },
          metrics = [
            ["AWS/Lambda", "Invocations", "FunctionName", var.extractor_lambda_name, { stat = "Sum", label = "Invocations", color = local.info }],
            ["AWS/Lambda", "Errors", "FunctionName", var.extractor_lambda_name, { stat = "Sum", label = "Errors", color = local.bad }],
            ["AWS/Lambda", "Throttles", "FunctionName", var.extractor_lambda_name, { stat = "Sum", label = "Throttles", color = local.warn }],
          ]
        }
      },
      {
        type = "metric", x = 8, y = 15, width = 8, height = 6,
        properties = {
          # Baselines (PR-019 runbook): cold start 756–1022 ms, handler 3.8–8.7 s,
          # network-bound on the loteria.org.gt scrape. Timeout is 120 s.
          title = "Extractor Lambda — duration",
          view  = "timeSeries", region = var.aws_region, period = 86400,
          yAxis = { left = { min = 0, label = "ms", showUnits = false } },
          metrics = [
            ["AWS/Lambda", "Duration", "FunctionName", var.extractor_lambda_name, { stat = "Average", label = "avg", color = local.info }],
            ["AWS/Lambda", "Duration", "FunctionName", var.extractor_lambda_name, { stat = "p95", label = "p95", color = local.warn }],
            ["AWS/Lambda", "Duration", "FunctionName", var.extractor_lambda_name, { stat = "Maximum", label = "max", color = local.bad }],
          ]
        }
      },
      {
        type = "metric", x = 16, y = 15, width = 8, height = 6,
        properties = {
          title = "Gold-purge Lambda (7 calls/run)",
          view  = "timeSeries", region = var.aws_region, period = 86400,
          yAxis = {
            left  = { min = 0, showUnits = false },
            right = { min = 0, label = "ms", showUnits = false }
          },
          metrics = [
            ["AWS/Lambda", "Invocations", "FunctionName", var.gold_purge_lambda_name, { stat = "Sum", label = "Invocations", color = local.info }],
            ["AWS/Lambda", "Errors", "FunctionName", var.gold_purge_lambda_name, { stat = "Sum", label = "Errors", color = local.bad }],
            ["AWS/Lambda", "Duration", "FunctionName", var.gold_purge_lambda_name, { stat = "Average", label = "Avg duration", color = local.mute, yAxis = "right" }],
          ]
        }
      },

      # --- Row 4: Athena / the gold layer ----------------------------------------------
      {
        type = "metric", x = 0, y = 21, width = 8, height = 6,
        properties = {
          # Cost proxy: Athena bills per byte scanned. The gold CTAS re-reads all of silver
          # on every run, so this is the line to watch if the bill moves.
          title = "Athena bytes scanned (${var.athena_workgroup_name})",
          view  = "timeSeries", region = var.aws_region, period = 86400,
          yAxis = { left = { min = 0, label = "bytes", showUnits = false } },
          metrics = [
            ["AWS/Athena", "ProcessedBytes", "WorkGroup", var.athena_workgroup_name, { stat = "Sum", label = "Bytes scanned", color = local.info }],
          ]
        }
      },
      {
        type = "metric", x = 8, y = 21, width = 8, height = 6,
        properties = {
          title = "Athena query timing",
          view  = "timeSeries", region = var.aws_region, period = 86400,
          yAxis = { left = { min = 0, label = "ms", showUnits = false } },
          metrics = [
            ["AWS/Athena", "EngineExecutionTime", "WorkGroup", var.athena_workgroup_name, "QueryState", "SUCCEEDED", "QueryType", "DDL", { stat = "Average", label = "Engine (DDL / CTAS)", color = local.info }],
            ["AWS/Athena", "QueryQueueTime", "WorkGroup", var.athena_workgroup_name, "QueryState", "SUCCEEDED", "QueryType", "DDL", { stat = "Average", label = "Queue (DDL / CTAS)", color = local.warn }],
            ["AWS/Athena", "QueryPlanningTime", "WorkGroup", var.athena_workgroup_name, "QueryState", "SUCCEEDED", "QueryType", "DDL", { stat = "Average", label = "Planning (DDL / CTAS)", color = local.alt }],
          ]
        }
      },
      {
        type = "metric", x = 16, y = 21, width = 8, height = 6,
        properties = {
          # There is no Athena "query count" metric. SampleCount on a timing metric IS the
          # count of queries that reported it, which makes SUCCEEDED-vs-FAILED countable.
          title = "Athena query outcomes (count)",
          view  = "timeSeries", stacked = true, region = var.aws_region, period = 86400,
          yAxis = { left = { min = 0, showUnits = false } },
          metrics = [
            ["AWS/Athena", "TotalExecutionTime", "WorkGroup", var.athena_workgroup_name, "QueryState", "SUCCEEDED", "QueryType", "DDL", { stat = "SampleCount", label = "Succeeded (DDL)", color = local.ok }],
            ["AWS/Athena", "TotalExecutionTime", "WorkGroup", var.athena_workgroup_name, "QueryState", "SUCCEEDED", "QueryType", "DML", { stat = "SampleCount", label = "Succeeded (DML)", color = local.info }],
            ["AWS/Athena", "TotalExecutionTime", "WorkGroup", var.athena_workgroup_name, "QueryState", "FAILED", "QueryType", "DDL", { stat = "SampleCount", label = "Failed (DDL)", color = local.bad }],
          ]
        }
      },

      # --- Row 5: logs — the only Glue-side visibility ---------------------------------
      {
        type = "log", x = 0, y = 27, width = 12, height = 7,
        properties = {
          # Glue publishes no metrics for this job type, so its health is read from logs.
          # PR-018's structured JSON makes correlation_id (= the SFN execution name) a
          # first-class field, so one line per run identifies which execution wrote it.
          title  = "Glue transform — recent structured log lines",
          region = var.aws_region,
          view   = "table",
          query  = "SOURCE '${var.glue_output_log_group_name}' | fields @timestamp, correlation_id, level, message, sorteo_number | filter ispresent(correlation_id) | sort @timestamp desc | limit 25"
        }
      },
      {
        type = "log", x = 12, y = 27, width = 12, height = 7,
        properties = {
          # /aws-glue/python-jobs/error carries stderr + tracebacks. Account-wide (PR-023
          # §3), but this account runs no other Python Shell job.
          title  = "Glue transform — errors & tracebacks",
          region = var.aws_region,
          view   = "table",
          query  = "SOURCE '${var.glue_error_log_group_name}' | fields @timestamp, @message | sort @timestamp desc | limit 25"
        }
      },
    ]
  })
}
