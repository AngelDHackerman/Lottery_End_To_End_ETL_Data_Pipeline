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

# PR-026.1 (correctness fix): the two silver crawlers are no longer fired and forgotten.
# They now run in a Parallel state, each branch polling GetCrawler until that crawl has
# demonstrably finished AND succeeded, before PrepGold/BuildGold may run. See the block
# comment on `RunSilverCrawlers` for the measured race this closes.

# PR-023 adds log retention here in two places: the gold-purge Lambda's own group (which
# already exists in prod and must be IMPORTED), and — new — a log group for the state
# machine itself. Step Functions writes execution logs only when a logging_configuration
# is attached, so until now the pipeline had no CloudWatch record of a run at all; the
# only history was the 90-day console execution list. See
# docs/runbooks/PR-023-log-retention.md.

locals {
  gold_sql_dir = "${path.module}/../../../sql/gold"
  # Baked at plan time: the Map iterates this static list, so the state machine never
  # has to list S3 at runtime. Each item feeds one purge -> CTAS iteration.
  gold_sql_keys = [
    for f in fileset(local.gold_sql_dir, "*.sql") : { sqlKey = "sql/gold/${f}" }
  ]

  # PR-023: declared as locals so each log group can be created BEFORE the resource that
  # writes to it (see the etl-lambda module for why the reverse order is a trap).
  gold_purge_function_name = "lottery-gold-purge-${var.environment}"
  state_machine_name       = "lottery-etl-pipeline-${var.environment}"
  sfn_logging_enabled      = var.sfn_log_level != "OFF"

  # PR-026.1: the two silver crawlers, keyed by the PascalCase fragment used to name their
  # states. A map (not a list) so the generated state names are stable — Terraform iterates
  # a map in lexical key order, so Premios always comes before Sorteos and the rendered
  # definition never churns.
  silver_crawlers = {
    Premios = var.premios_crawler_name
    Sorteos = var.sorteos_crawler_name
  }

  # PR-026.1: one Parallel branch per crawler. Each branch is
  #   baseline -> start -> (wait -> get -> check)* -> verify -> succeed
  # See the block comment above `RunSilverCrawlers` for why every piece is here.
  crawler_branches = [
    for key, crawler_name in local.silver_crawlers : {
      StartAt = "Baseline${key}Crawler"
      States = {
        # 1. Record which crawl was the most recent BEFORE we start ours. This is what makes
        #    "State == READY" trustworthy: READY is also the state a crawler sits in during
        #    the moments between StartCrawler returning and the control plane flipping it to
        #    RUNNING. Without a baseline, the first poll could read that stale READY and
        #    declare a crawl finished before it had begun — the exact class of bug this PR
        #    exists to kill. `MessagePrefix` is the crawl's own UUID, so a changed value is
        #    positive proof that a NEW crawl ran to completion.
        "Baseline${key}Crawler" = {
          Type     = "Task",
          Resource = "arn:aws:states:::aws-sdk:glue:getCrawler",
          Parameters = {
            Name = crawler_name
          },
          ResultPath = "$.baseline",
          Retry      = local.crawler_get_retry,
          Next       = "Start${key}Crawler"
        },

        # 2. Start the crawl. `ResultPath = null` discards startCrawler's empty response so
        #    the baseline recorded above survives into the poll loop.
        "Start${key}Crawler" = {
          Type     = "Task",
          Resource = "arn:aws:states:::aws-sdk:glue:startCrawler",
          Parameters = {
            Name = crawler_name
          },
          ResultPath = null,
          Next       = "Init${key}Poll"
        },

        # 3. Seed the attempt counter used by the budget guard in step 6.
        "Init${key}Poll" = {
          Type       = "Pass",
          Result     = { attempts = 0 },
          ResultPath = "$.poll",
          Next       = "Wait${key}Crawler"
        },

        # 4. Sleep, then look again. The wait comes FIRST: polling immediately after
        #    StartCrawler only burns an API call, since the fastest observed crawl still
        #    takes minutes.
        "Wait${key}Crawler" = {
          Type    = "Wait",
          Seconds = var.crawler_poll_interval_seconds,
          Next    = "Get${key}Crawler"
        },

        "Get${key}Crawler" = {
          Type     = "Task",
          Resource = "arn:aws:states:::aws-sdk:glue:getCrawler",
          Parameters = {
            Name = crawler_name
          },
          ResultPath = "$.current",
          Retry      = local.crawler_get_retry,
          Next       = "Check${key}Crawler"
        },

        # 5. Are we done? Two ways to be done, because a crawler that has NEVER run has no
        #    `LastCrawl` block at all to compare against (the fresh-account case — this
        #    account's crawlers have 100+ crawls, but a clone would not). Every comparison
        #    is guarded by `IsPresent` first, which is the pattern AWS documents for
        #    referencing a field that may be absent.
        "Check${key}Crawler" = {
          Type = "Choice",
          Choices = [
            # 5a. Fresh account: no crawl existed before, one exists now and we are idle.
            {
              And = [
                { Variable = "$.current.Crawler.State", StringEquals = "READY" },
                { Variable = "$.baseline.Crawler.LastCrawl", IsPresent = false },
                { Variable = "$.current.Crawler.LastCrawl", IsPresent = true },
              ],
              Next = "Verify${key}Crawl"
            },
            # 5b. Steady state: idle AND the last crawl is a different crawl than the one
            #     that was last when we started.
            {
              And = [
                { Variable = "$.current.Crawler.State", StringEquals = "READY" },
                { Variable = "$.baseline.Crawler.LastCrawl.MessagePrefix", IsPresent = true },
                { Variable = "$.current.Crawler.LastCrawl.MessagePrefix", IsPresent = true },
                {
                  Not = {
                    Variable         = "$.current.Crawler.LastCrawl.MessagePrefix",
                    StringEqualsPath = "$.baseline.Crawler.LastCrawl.MessagePrefix"
                  }
                },
              ],
              Next = "Verify${key}Crawl"
            },
            # 5c. Budget exhausted — fail loudly rather than loop forever.
            {
              Variable                 = "$.poll.attempts",
              NumericGreaterThanEquals = var.crawler_poll_max_attempts,
              Next                     = "${key}CrawlTimedOut"
            },
          ],
          Default = "Increment${key}Poll"
        },

        # 6. Not done yet: count the attempt and go back to sleep.
        "Increment${key}Poll" = {
          Type = "Pass",
          Parameters = {
            "attempts.$" = "States.MathAdd($.poll.attempts, 1)"
          },
          ResultPath = "$.poll",
          Next       = "Wait${key}Crawler"
        },

        # 7. The crawl finished — but "finished" is not "succeeded". A FAILED crawl leaves
        #    the catalog exactly as stale as no crawl at all, so letting the pipeline
        #    proceed here would reintroduce the defect through the back door. Failing the
        #    execution also gives the run an owner: PR-025's SFN_ExecutionFailed alarm.
        "Verify${key}Crawl" = {
          Type = "Choice",
          Choices = [
            {
              Variable     = "$.current.Crawler.LastCrawl.Status",
              StringEquals = "SUCCEEDED",
              Next         = "${key}CrawlSucceeded"
            },
          ],
          Default = "${key}CrawlFailed"
        },

        "${key}CrawlTimedOut" = {
          Type  = "Fail",
          Error = "CrawlerPollTimeout",
          Cause = "The ${key} silver crawler did not return to READY within the poll budget (crawler_poll_interval_seconds x crawler_poll_max_attempts). Gold was NOT built, because a CTAS against a half-updated catalog would silently produce wrong data. Check the crawler in the Glue console and /aws-glue/crawlers."
        },

        "${key}CrawlFailed" = {
          Type  = "Fail",
          Error = "CrawlerRunFailed",
          Cause = "The ${key} silver crawler finished with a LastCrawl.Status other than SUCCEEDED. Gold was NOT built: a failed crawl leaves the Glue catalog missing this run's new (year, sorteo) partition, so the CTAS would have produced gold tables without the newest sorteo. See /aws-glue/crawlers."
        },

        "${key}CrawlSucceeded" = {
          Type = "Succeed"
        },
      }
    }
  ]

  # Polling adds up to `2 x crawler_poll_max_attempts` GetCrawler calls per run. Glue
  # throttles per-account, and this pipeline shares the account with another project, so a
  # short backoff on the read is cheap insurance. Deliberately narrow: EntityNotFound or a
  # malformed request must fail fast, not retry.
  crawler_get_retry = [
    {
      ErrorEquals = [
        "Glue.ThrottlingException",
        "Glue.OperationTimeoutException",
        "Glue.InternalServiceException",
      ],
      IntervalSeconds = 5,
      MaxAttempts     = 3,
      BackoffRate     = 2
    }
  ]
}

resource "aws_cloudwatch_log_group" "gold_purge" {
  name              = "/aws/lambda/${local.gold_purge_function_name}"
  retention_in_days = var.log_retention_days

  tags = {
    Name        = "/aws/lambda/${local.gold_purge_function_name}"
    Environment = var.environment
    Project     = "Lottery ETL"
    Owner       = "Angel Hackerman"
  }
}

# Step Functions delivers execution logs through CloudWatch Logs' "vended logs" path, which
# requires the group name to start with /aws/vendedlogs/ — any other prefix is accepted by
# Terraform but rejected by the service when it tries to create the delivery.
resource "aws_cloudwatch_log_group" "state_machine" {
  count = local.sfn_logging_enabled ? 1 : 0

  name              = "/aws/vendedlogs/states/${local.state_machine_name}"
  retention_in_days = var.log_retention_days

  tags = {
    Name        = "/aws/vendedlogs/states/${local.state_machine_name}"
    Environment = var.environment
    Project     = "Lottery ETL"
    Owner       = "Angel Hackerman"
  }
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
  function_name    = local.gold_purge_function_name
  filename         = data.archive_file.gold_purge.output_path
  source_code_hash = data.archive_file.gold_purge.output_base64sha256
  handler          = "purge_and_load.handler"
  runtime          = "python3.12"
  timeout          = 120
  memory_size      = 256
  role             = var.gold_purge_lambda_role_arn

  # PR-023: same ordering rule as the extractor — group first, function second.
  depends_on = [aws_cloudwatch_log_group.gold_purge]

  tags = {
    Name        = local.gold_purge_function_name
    Environment = var.environment
    Project     = "Lottery ETL"
    Owner       = "Angel Hackerman"
  }
}

# =======================================================================================
# PR-033 — the Silver data-quality gate, rendered conditionally
# =======================================================================================
locals {
  # The gate is itself gated. With enable_silver_dq = false the crawlers flow straight to
  # PrepGold as before and none of the three states below are rendered, so the stack stays
  # deployable before scripts/build_dq_package.sh has produced and uploaded the artifacts.
  after_crawlers = var.enable_silver_dq ? "RunSilverDQ" : "PrepGold"

  pipeline_comment = var.enable_silver_dq ? (
    "Run ETL pipeline: extractor Lambda → transformer Glue → silver crawlers → silver DQ gate → gold CTAS"
    ) : (
    "Run ETL pipeline: extractor Lambda → transformer Glue → silver crawlers → gold CTAS"
  )

  # ⚠️ Gated as a JSON *string*, then decoded — NOT as `var.enable_silver_dq ? {...} : {}`.
  #
  # Terraform requires both branches of a conditional to unify to one type, and an ASL state
  # map is heterogeneous by construction: a Task state has Resource/Parameters/Catch, a Fail
  # state has Error/Cause, and they share no attributes. The direct form fails with "the
  # 'true' value includes object attribute \"SilverDQFailed\", which is absent in the 'false'
  # value" — the object types genuinely differ, so this is not a workaround for a Terraform
  # quirk but for a real type mismatch. Gating a string sidesteps unification entirely, and
  # jsondecode hands back a map that merge() accepts.
  #
  # The payoff is exactness: with the flag off, the rendered definition is byte-identical to
  # the pre-PR-033 one, so turning the gate off is a genuine no-op rather than "almost the
  # same machine".
  dq_states = jsondecode(var.enable_silver_dq ? local.dq_states_json : "{}")

  dq_states_json = jsonencode({
    # PR-033 — THE DATA-QUALITY GATE. This is the state that sits between a Silver layer
    # that has just been (re)catalogued and the seven CTAS that aggregate it.
    #
    # WHY IT IS HERE AND NOT ANYWHERE ELSE.
    #   - AFTER the crawlers, not before: the DQ job reads Parquet straight from S3 with
    #     boto3, so strictly it does not need the catalog. But running it after means a
    #     green verdict describes the exact state Gold is about to read, which is the only
    #     claim worth making. It also inherits PR-026.1's guarantee that the crawl actually
    #     finished, so "DQ passed but Gold missed the newest sorteo" cannot happen.
    #   - BEFORE BuildGold, unconditionally: this is the whole point. `loteria.gold.
    #     purge_and_load` DROPs each gold table and empties its S3 prefix before the CTAS
    #     writes it, so letting a bad Silver through does not merely produce wrong Gold —
    #     it destroys the last known-good Gold on the way. The gate protects the old data
    #     as much as the new.
    #
    # `.sync` (not the fire-and-forget form): unlike startCrawler, glue:startJobRun HAS a
    # .sync integration, so this task really does wait for the job to finish and fails
    # when the job fails. No polling loop is needed here — contrast local.crawler_branches,
    # which exists precisely because startCrawler lacks this.
    #
    # ResultPath = null throws the Glue run summary away: BuildGold's input must stay
    # exactly what PrepGold expects, and the verdict belongs in the job log, not in the
    # execution payload (a full report would also push toward the 256 KB state limit).
    RunSilverDQ = {
      Type     = "Task",
      Resource = "arn:aws:states:::glue:startJobRun.sync",
      Parameters = {
        JobName = var.dq_glue_job_name,
        Arguments = {
          "--PARTITIONED_BUCKET" = var.partitioned_bucket_name,
          # PR-018: same correlation id as every other stage, so the DQ verdict can be
          # stitched to the extractor and transformer logs it is judging.
          "--CORRELATION_ID.$" = "$$.Execution.Name"
        }
      },
      ResultPath = null,

      # Deliberately NO Retry. Every other Task in this machine retries, so the absence is
      # a decision, not an omission: a failed expectation is deterministic — the same
      # immutable Silver layer validated twice gives the same verdict — so a retry would
      # burn a second Glue run to reach the identical conclusion, and would delay the
      # alert by however long the job takes. Infrastructure flakes (a Glue capacity error)
      # are the one case a retry would help, and they arrive as a failed execution the
      # owner can restart by hand, which is rare enough not to design around.
      Catch = [
        {
          ErrorEquals = ["States.ALL"],
          # Keep the error object — NotifyDQFailure reads $.dqError.Cause for the message.
          ResultPath = "$.dqError",
          Next       = "NotifyDQFailure"
        }
      ],
      Next = "PrepGold"
    },

    # Publish the detail, THEN fail.
    #
    # PR-025's sfn_execution_failed alarm already fires on any failed execution, so this
    # state is not what makes the failure visible — it is what makes it actionable. That
    # alarm's message is "an execution failed"; this one carries Glue's ErrorMessage, which
    # for a Python exception is the exception's string, which `loteria.dq.glue_entrypoint`
    # deliberately builds out of `summarize_failures()`: the suite, the expectation and the
    # column. The difference is reading an email versus opening three console tabs.
    #
    # It also distinguishes the two failure modes the entry point separates: a genuine
    # expectation failure, and "there is no Silver data here", which means a wrong bucket
    # or a transformer that never ran, and needs a completely different response.
    NotifyDQFailure = {
      Type     = "Task",
      Resource = "arn:aws:states:::sns:publish",
      Parameters = {
        TopicArn    = var.alerts_topic_arn,
        Subject     = "[Loteria ${var.environment}] Silver DQ FAILED - Gold was not built",
        "Message.$" = "States.Format('The Silver data-quality gate failed. The Gold layer was NOT rebuilt, and the previous Gold tables are intact.\n\nExecution: {}\nDetail: {}\n\nFull verdict: log group ${var.dq_log_group_name}', $$.Execution.Name, $.dqError.Cause)"
      },
      # If SNS itself is the thing that is broken, still fail the execution — the alarm is
      # the backstop. Swallowing this would turn a DQ failure into a silent success.
      ResultPath = null,
      Catch = [
        {
          ErrorEquals = ["States.ALL"],
          ResultPath  = null,
          Next        = "SilverDQFailed"
        }
      ],
      Next = "SilverDQFailed"
    },

    SilverDQFailed = {
      Type  = "Fail",
      Error = "SilverDataQualityFailed",
      Cause = "The Silver layer failed its Great Expectations suites, so the Gold CTAS map state was skipped. This is a SUCCESSFUL gate, not a broken pipeline: Gold still holds last week's data, which is correct data, and the purge that would have destroyed it never ran. Read the verdict in ${var.dq_log_group_name} — it names every failed expectation and its column. Fix Silver (re-scrape the affected sorteo, or fix the parser), then re-run the state machine."
    }
  })
}

resource "aws_sfn_state_machine" "pipeline_state_machine" {
  name     = local.state_machine_name
  role_arn = var.sfn_execution_role_arn

  # PR-023: turn on execution logging. Off by default in AWS, which is why no
  # /aws/vendedlogs/states/ group existed before this PR. `:*` on the destination is
  # required — Step Functions delivers to the log group's stream wildcard, and the API
  # rejects a bare group ARN.
  dynamic "logging_configuration" {
    for_each = local.sfn_logging_enabled ? [1] : []
    content {
      log_destination        = "${aws_cloudwatch_log_group.state_machine[0].arn}:*"
      include_execution_data = var.sfn_include_execution_data
      level                  = var.sfn_log_level
    }
  }

  definition = jsonencode({
    Comment = local.pipeline_comment,
    StartAt = "RunExtractorLambda",
    # PR-033: the gate's three states are merged in rather than written inline, so that
    # enable_silver_dq = false renders exactly the pre-PR-033 definition — local.dq_states is
    # an empty map and local.after_crawlers points the crawlers back at PrepGold.
    States = merge(local.dq_states, {
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

        # PR-031.1: the extractor had NO retry at all. One 25 s timeout and the whole
        # weekly execution died — and because the trigger runs once a week, each transient
        # blip cost a full sorteo that nothing ever went back for. Both the 2026-08-20 and
        # 2026-08-27 runs failed this way, ~26 s after starting.
        #
        # The error list is deliberate rather than States.ALL. A retry is not free here:
        # every attempt costs 2 proxied requests at 25 credits each on a 1000/month plan
        # (PR-031.1 raised the per-request cost 25x), so retrying a deterministic bug —
        # a parser failure, a missing selector — would just burn quota to fail three times
        # instead of once. Listed here are the errors a second attempt can actually fix:
        # network faults from `requests`, and Lambda's own transient service errors.
        #
        # Retrying is safe: extract_lottery_data() calls check_if_sorteo_exists() and
        # returns without writing when the sorteo is already in S3, so a retry after a
        # partial success is a no-op rather than a duplicate.
        #
        # 60 s / 2 attempts / 2.0 backoff = attempts at t+0, t+60, t+180. The Cloudflare
        # block this PR fixes was persistent, so retries would NOT have saved those two
        # runs — this is for the transient case, and the runbook says so plainly.
        Retry = [
          {
            ErrorEquals = [
              "ReadTimeout",
              "ConnectTimeout",
              "ConnectionError",
              "Lambda.ServiceException",
              "Lambda.AWSLambdaException",
              "Lambda.SdkClientException",
              "Lambda.TooManyRequestsException",
            ],
            IntervalSeconds = 60,
            MaxAttempts     = 2,
            BackoffRate     = 2.0
          }
        ],

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
        Next = "RunSilverCrawlers"
      },

      # PR-026.1 — THE FIX. Previously this was two back-to-back
      # `aws-sdk:glue:startCrawler` tasks that flowed straight into PrepGold.
      #
      # There is no `.sync` variant of startCrawler, so those tasks completed the instant
      # the API call was ACCEPTED, not when the crawl finished. The gold CTAS then raced
      # the crawlers. Measured on the 2026-07-30 run: `RunSorteosCrawler` returned at
      # 15:01:48.9, the first 2 of 7 CTAS started at 15:02:02.2, and the crawler only wrote
      # the catalog at 15:02:55 — those two CTAS read a catalog 53 s stale. Which two lose
      # the race depends on Map scheduling, so the stale table was non-deterministic.
      #
      # It matters because silver is partitioned by (year, sorteo): every weekly run creates
      # a BRAND-NEW partition, invisible to Athena until a crawler registers it. This is not
      # the ordinary "new files inside a known partition" case that Athena resolves on its
      # own. The failure is silent — no error, no alarm, just a gold table missing the
      # newest draw.
      #
      # Two changes:
      #   - Parallel instead of sequential. The crawlers were already started back-to-back
      #     and both must finish before gold can build, so waiting for them one after the
      #     other would have added ~4.5 min of dead time for nothing. Parallel makes the new
      #     wait cost roughly one crawl, not two.
      #   - Each branch polls to completion (see local.crawler_branches).
      #
      # `Parameters = {}` starts each branch from a tiny object instead of the Glue job's
      # response, and `ResultPath = null` throws the branch outputs away — so PrepGold
      # receives exactly what it did before and the payload stays far from the 256 KB limit.
      RunSilverCrawlers = {
        Type       = "Parallel",
        Parameters = {},
        ResultPath = null,
        Branches   = local.crawler_branches,
        Next       = local.after_crawlers
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

      # One iteration per gold table: prepare -> CTAS -> promote (PR-042.1, blue/green).
      # MaxConcurrency caps parallel Athena CTAS; the 7 tables are independent (all read
      # only silver_*), so parallelism is safe.
      #
      # ⚠️ The ORDER is the fix. Before PR-042.1 the first state dropped the table and
      # emptied its S3 prefix, so a CTAS failure left nothing behind — a seven-day hole
      # until the next Thursday. Now nothing published is touched until PromoteGold, which
      # only runs when the CTAS has already succeeded. A failed run leaves the previous
      # generation serving reads, untouched.
      BuildGold = {
        Type           = "Map",
        ItemsPath      = "$.gold.sqlKeys",
        MaxConcurrency = 3,
        Iterator = {
          StartAt = "PrepareGold",
          States = {
            PrepareGold = {
              Type     = "Task",
              Resource = "arn:aws:states:::lambda:invoke",
              Parameters = {
                FunctionName = aws_lambda_function.gold_purge.arn,
                Payload = {
                  "action"           = "prepare",
                  "bucket"           = var.partitioned_bucket_name,
                  "sqlKey.$"         = "$.sqlKey",
                  "correlation_id.$" = "$$.Execution.Name"
                }
              },
              # Lift the Lambda's return out of the invoke envelope. Everything but the
              # query string is carried through the CTAS so PromoteGold knows what it is
              # promoting and where from — the state machine never derives those names
              # itself, which keeps the SQL file the single source of truth.
              ResultSelector = {
                "queryString.$"  = "$.Payload.queryString",
                "database.$"     = "$.Payload.database",
                "table.$"        = "$.Payload.table",
                "stagingTable.$" = "$.Payload.stagingTable",
                "location.$"     = "$.Payload.location"
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
              # ResultPath keeps the prepare output alive: Athena's response would otherwise
              # replace the state input, and PromoteGold would have nothing to act on.
              ResultPath = "$.ctas",
              Next       = "PromoteGold"
            },
            # The swap. One glue:UpdateTable on the published table, then its partitions are
            # moved onto the new generation. The previous generation stays in S3 — retiring
            # it is PR-042.2, deliberately separate, because a delete that runs before the
            # swap is the defect this PR removes.
            PromoteGold = {
              Type     = "Task",
              Resource = "arn:aws:states:::lambda:invoke",
              Parameters = {
                FunctionName = aws_lambda_function.gold_purge.arn,
                Payload = {
                  "action"           = "promote",
                  "database.$"       = "$.database",
                  "table.$"          = "$.table",
                  "stagingTable.$"   = "$.stagingTable",
                  "correlation_id.$" = "$$.Execution.Name"
                }
              },
              ResultSelector = {
                "table.$"      = "$.Payload.table",
                "location.$"   = "$.Payload.location",
                "partitions.$" = "$.Payload.partitions"
              },
              End = true
            }
          }
        },
        End = true
      }
    })
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
