# Module: iam
# All IAM roles, customer-managed policies, and attachments for the pipeline.
# Migrated from terraform-lottery/Prod/{iam.tf, iam_stepFunctions_eventBridge.tf} in
# PR-009 via cross-state `terraform state rm` (legacy) + `terraform import` (here) — no
# role/policy is recreated. See docs/runbooks/PR-009-iam-migration.md.
#
# PR-009 also TIGHTENS three previously-wildcarded grants (applied in-place after import,
# NOT a no-op — see runbook):
#   - lambda + glue secretsmanager access  -> the single lottery secret ARN
#   - Step Function glue:* job actions      -> the specific transform job ARN
#   - Step Function glue:* crawler actions  -> the two silver crawler ARNs
# The personal IAM-user athena grants are gated behind var.personal_iam_users (default
# empty), so a fresh cloner gets none.

data "aws_caller_identity" "current" {}

# Resolve the lottery secret ARN by name (portable across accounts — the random suffix
# and account id are filled in by AWS, so policies stay exact without hard-coding).
data "aws_secretsmanager_secret" "lottery" {
  name = var.secret_name
}

locals {
  account_id = data.aws_caller_identity.current.account_id

  # ARNs for the resources the Step Function drives. Constructed from names here; PR-010
  # (etl-lambda), PR-011 (etl-glue) and PR-012 (catalog/orchestration) will swap these for
  # the real module outputs once those modules exist.
  extractor_lambda_arn = "arn:aws:lambda:${var.aws_region}:${local.account_id}:function:${var.extractor_lambda_name}"
  glue_job_arn         = "arn:aws:glue:${var.aws_region}:${local.account_id}:job/${var.glue_job_name}"
  silver_crawler_arns = [
    "arn:aws:glue:${var.aws_region}:${local.account_id}:crawler/${var.glue_crawler_premios_name}",
    "arn:aws:glue:${var.aws_region}:${local.account_id}:crawler/${var.glue_crawler_sorteos_name}",
  ]
  state_machine_arn = "arn:aws:states:${var.aws_region}:${local.account_id}:stateMachine:lottery-etl-pipeline-${var.environment}"

  # PR-023: the Step Functions execution log group (created in the orchestration module).
  # Built from the name here rather than passed in as an output, to keep the existing
  # iam -> orchestration dependency direction (orchestration consumes IAM, never both ways).
  sfn_log_group_arn = "arn:aws:logs:${var.aws_region}:${local.account_id}:log-group:/aws/vendedlogs/states/lottery-etl-pipeline-${var.environment}"

  # PR-022 gold layer ARNs.
  gold_purge_lambda_arn = "arn:aws:lambda:${var.aws_region}:${local.account_id}:function:lottery-gold-purge-${var.environment}"
  athena_workgroup_arn  = "arn:aws:athena:${var.aws_region}:${local.account_id}:workgroup/${var.athena_workgroup_name}"
  glue_catalog_arn      = "arn:aws:glue:${var.aws_region}:${local.account_id}:catalog"
  glue_database_arn     = "arn:aws:glue:${var.aws_region}:${local.account_id}:database/${var.database_name}"
  glue_tables_arn       = "arn:aws:glue:${var.aws_region}:${local.account_id}:table/${var.database_name}/*"
}

# ===========================================================================
# ROLES
# ===========================================================================

# Role for Lambdas
resource "aws_iam_role" "lambda_exec" {
  name = "lottery-lambda-exec-role${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow",
      Principal = { Service = "lambda.amazonaws.com" },
      Action    = "sts:AssumeRole"
    }]
  })
}

# Role for AWS Glue Job
data "aws_iam_policy_document" "glue_assume_role_policy" {
  statement {
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["glue.amazonaws.com"]
    }
    actions = ["sts:AssumeRole"]
  }
}

resource "aws_iam_role" "glue_job_role" {
  name               = "glue-lottery-transform-role-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.glue_assume_role_policy.json
}

# Role for AWS Glue Crawler
resource "aws_iam_role" "glue_crawler_role" {
  name = "glue-crawler-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Action = "sts:AssumeRole",
      Principal = {
        Service = "glue.amazonaws.com"
      },
      Effect = "Allow",
      Sid    = ""
    }]
  })
}

# Role for SageMaker Studio
resource "aws_iam_role" "sagemaker_execution_role" {
  name = "lottery-sagemaker-execution-role-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect = "Allow",
      Principal = {
        Service = "sagemaker.amazonaws.com"
      },
      Action = "sts:AssumeRole"
    }]
  })

  tags = {
    Name = "lottery-sagemaker-role-${var.environment}"
  }
}

# Role for Step Functions State Machine
resource "aws_iam_role" "sfn_execution_role" {
  name = "sfn-lottery-execution-role-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Principal = {
          Service = "states.amazonaws.com"
        },
        Action = "sts:AssumeRole"
      }
    ]
  })
}

# Role for EventBridge -> Step Functions
resource "aws_iam_role" "eventbridge_to_sfn_role" {
  name = "eventbridge-to-sfn-role-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Principal = {
          Service = "events.amazonaws.com"
        },
        Action = "sts:AssumeRole"
      }
    ]
  })
}

# Role for the gold-purge Lambda (PR-022): drops each gold table + empties its S3 prefix
# before the CTAS. Separate from the extractor role so its blast radius is just the gold
# prefix + the catalog tables it recreates.
resource "aws_iam_role" "gold_purge_lambda" {
  name = "lottery-gold-purge-role-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Effect    = "Allow",
      Principal = { Service = "lambda.amazonaws.com" },
      Action    = "sts:AssumeRole"
    }]
  })
}

# ===========================================================================
# CUSTOMER-MANAGED POLICIES
# ===========================================================================

# SageMaker S3 read-only for the simple/EDA dataset
resource "aws_iam_policy" "sagemaker_s3_read_policy" {
  name        = "lottery-sagemaker-s3-read-policy-${var.environment}"
  description = "Allows SageMaker to read raw and processed data"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow",
        Action = [
          "s3:GetObject",
          "s3:ListBucket"
        ],
        Resource = [
          var.simple_bucket_arn,
          "${var.simple_bucket_arn}/*"
        ]
      }
    ]
  })
}

# SageMaker Studio admin (list/describe apps, domains, spaces, ...)
resource "aws_iam_policy" "sagemaker_studio_admin_policy" {
  name        = "lottery-sagemaker-studio-admin-policy-${var.environment}"
  description = "Policy to allow SageMaker Studio to list and describe apps, domains, spaces, etc."

  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Action = [
          "sagemaker:ListApps",
          "sagemaker:DescribeApp",
          "sagemaker:CreatePresignedDomainUrl",
          "sagemaker:ListUserProfiles",
          "sagemaker:ListDomains",
          "sagemaker:DescribeDomain",
          "sagemaker:ListSpaces",
          "sagemaker:DescribeUserProfile",
          "sagemaker:DescribeSpace",
          "sagemaker:AddTags",
          "sagemaker:CreateSpace",
          "sagemaker:UpdateSpace",
          "sagemaker:CreateApp",
          "sagemaker:DeleteApp",
          "sagemaker:DeleteSpace"
        ],
        Resource = "*"
      }
    ]
  })
}

# Glue crawler -> S3 (partitioned bucket + athena results)
resource "aws_iam_policy" "glue_crawler_s3_policy" {
  name        = "glue-crawler-s3-access"
  description = "Allow Glue crawler to access partitioned lottery bucket"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow",
        Action = [
          "s3:GetObject",
          "s3:ListBucket"
        ],
        Resource = [
          var.partitioned_bucket_arn,
          "${var.partitioned_bucket_arn}/*",

          "arn:aws:s3:::${var.athena_results_bucket_name}",
          "arn:aws:s3:::${var.athena_results_bucket_name}/*"
        ]
      }
    ]
  })
}

# Glue Job: S3 + Logs + Secrets + script zip
data "aws_iam_policy_document" "glue_job_policy" {
  statement {
    sid    = "AllowS3Access"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:ListBucket",
      "s3:DeleteObject",
      "s3:HeadObject"
    ]
    resources = [
      var.partitioned_bucket_arn,
      "${var.partitioned_bucket_arn}/*",
      var.simple_bucket_arn,
      "${var.simple_bucket_arn}/*"
    ]
  }

  statement {
    sid    = "AllowCloudWatchLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents"
    ]
    # PR-023: narrowed from "*" to the Glue log-group namespace. Deliberately the whole
    # /aws-glue/ prefix rather than just python-jobs/{output,error}: Glue picks the group
    # by job type (a pythonshell job writes to /aws-glue/python-jobs/*, a Spark one to
    # /aws-glue/jobs/*), so pinning the two exact groups would silently break logging the
    # day the job type changes — which is exactly the L6 migration this repo has queued.
    resources = [
      "arn:aws:logs:${var.aws_region}:${local.account_id}:log-group:/aws-glue/*",
      "arn:aws:logs:${var.aws_region}:${local.account_id}:log-group:/aws-glue/*:log-stream:*",
    ]
  }

  statement {
    sid       = "AllowSecretsManager"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [data.aws_secretsmanager_secret.lottery.arn] # PR-009: narrowed from "*"
  }

  statement {
    sid    = "AllowGlueToAccessScriptZip"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:HeadObject"
    ]
    resources = [
      "arn:aws:s3:::${var.lambda_code_bucket_name}",
      "arn:aws:s3:::${var.lambda_code_bucket_name}/*"
    ]
  }

  statement {
    sid    = "AllowListBucketPartitioned"
    effect = "Allow"
    actions = [
      "s3:ListBucket"
    ]
    resources = [
      var.partitioned_bucket_arn
    ]
  }
}

resource "aws_iam_policy" "glue_job_policy" {
  name   = "glue-lottery-transform-policy-${var.environment}"
  policy = data.aws_iam_policy_document.glue_job_policy.json
}

# Lambda: S3 + Secrets
data "aws_iam_policy_document" "lambda_custom_doc" {
  statement {
    sid    = "S3Access"
    effect = "Allow"

    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:ListBucket",
      "s3:HeadObject"
    ]

    resources = [
      var.partitioned_bucket_arn,
      "${var.partitioned_bucket_arn}/*",
      var.simple_bucket_arn,
      "${var.simple_bucket_arn}/*"
    ]
  }

  statement {
    sid    = "SecretsManagerAccess"
    effect = "Allow"
    actions = [
      "secretsmanager:GetSecretValue",
      "secretsmanager:DescribeSecret"
    ]
    resources = [data.aws_secretsmanager_secret.lottery.arn] # PR-009: narrowed from "*"
  }

  # PR-026: the extractor publishes the scrape.do HTTP status as a custom metric
  # (loteria.common.metrics). cloudwatch:PutMetricData supports NO resource-level
  # permissions, so `resources` must be "*" — but it does support the
  # `cloudwatch:namespace` condition key, which is the real scope: this role can write
  # only into our own namespace, not into AWS/* or any other application's metrics.
  statement {
    sid       = "PublishCustomMetrics"
    effect    = "Allow"
    actions   = ["cloudwatch:PutMetricData"]
    resources = ["*"]

    condition {
      test     = "StringEquals"
      variable = "cloudwatch:namespace"
      values   = [var.metrics_namespace]
    }
  }
}

resource "aws_iam_policy" "lambda_custom" {
  name   = "lottery-lambda-custom${var.environment}"
  policy = data.aws_iam_policy_document.lambda_custom_doc.json
}

# Athena results access (attached to personal users, gated below)
resource "aws_iam_policy" "athena_results_access" {
  name = "athena-results-s3-access"
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Effect = "Allow",
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket"
        ],
        Resource = [
          "arn:aws:s3:::${var.athena_results_bucket_name}",
          "arn:aws:s3:::${var.athena_results_bucket_name}/*"
        ]
      }
    ]
  })
}

# Gold-purge Lambda policy (PR-022): read the SQL under sql/gold/, empty the gold/<name>/
# prefix, and drop the gold table from the catalog. Scoped to the partitioned bucket +
# this database's tables.
resource "aws_iam_policy" "gold_purge_lambda_policy" {
  name = "lottery-gold-purge-policy-${var.environment}"

  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Sid    = "ReadGoldSqlAndData",
        Effect = "Allow",
        Action = [
          "s3:GetObject",
          "s3:ListBucket",
          # ListBucketVersions: the purge enumerates object versions + delete-markers to
          # hard-empty the gold prefix on this versioned bucket.
          "s3:ListBucketVersions"
        ],
        Resource = [
          var.partitioned_bucket_arn,
          "${var.partitioned_bucket_arn}/*"
        ]
      },
      {
        Sid    = "EmptyGoldPrefix",
        Effect = "Allow",
        Action = [
          "s3:DeleteObject",
          # DeleteObjectVersion: remove the actual versions (not just add a delete-marker)
          # so Athena CTAS sees a physically empty location. Gold is reproducible.
          "s3:DeleteObjectVersion"
        ],
        # Only the gold/ prefix — the purge never touches raw/ or silver/.
        Resource = "${var.partitioned_bucket_arn}/gold/*"
      },
      {
        Sid    = "DropGoldTable",
        Effect = "Allow",
        Action = [
          "glue:GetTable",
          "glue:DeleteTable"
        ],
        Resource = [
          local.glue_catalog_arn,
          local.glue_database_arn,
          local.glue_tables_arn
        ]
      }
    ]
  })
}

# Step Function execution policy (glue actions narrowed in PR-009)
resource "aws_iam_policy" "sfn_execution_policy" {
  name = "sfn-lottery-policy-${var.environment}"

  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Sid : "AllowInvokeExtractorLambda",
        Effect : "Allow",
        Action : [
          "lambda:InvokeFunction"
        ],
        Resource : local.extractor_lambda_arn
      },

      # Glue Job (start + polling + optional abort)
      {
        Sid : "AllowGlueJobExecution",
        Effect : "Allow",
        Action : [
          "glue:StartJobRun",
          "glue:GetJobRun",
          "glue:GetJobRuns",
          "glue:BatchStopJobRun"
        ],
        Resource : local.glue_job_arn # PR-009: narrowed from "*"
      },
      {
        Sid : "AllowStartGlueCrawlers",
        Effect : "Allow",
        Action : [
          "glue:StartCrawler",
          "glue:GetCrawler"
        ],
        Resource : local.silver_crawler_arns # PR-009: narrowed from "*"
      },
      # PR-023 turns on Step Functions execution logging, which needs TWO grants that look
      # redundant but are not.
      #
      # (1) The vended-logs DELIVERY setup. Step Functions does not write to CloudWatch
      # directly — it provisions a log delivery, and the CreateLogDelivery family plus
      # PutResourcePolicy are what authorize that. AWS documents these actions as not
      # supporting resource-level permissions, so Resource MUST stay "*": this is a
      # service constraint, not an un-narrowed wildcard. (Resolves the PR-009 TODO by
      # establishing that the scoping has to live in (2).)
      {
        Sid    = "AllowSfnLogDeliverySetup",
        Effect = "Allow",
        Action = [
          "logs:CreateLogDelivery",
          "logs:GetLogDelivery",
          "logs:UpdateLogDelivery",
          "logs:DeleteLogDelivery",
          "logs:ListLogDeliveries",
          "logs:PutResourcePolicy",
          "logs:DescribeResourcePolicies",
          "logs:DescribeLogGroups"
        ],
        Resource = "*"
      },
      # (2) The actual writes, scoped to the vended-logs namespace this stack owns.
      {
        Sid    = "LogsForSFN",
        Effect = "Allow",
        Action = [
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ],
        Resource = [
          local.sfn_log_group_arn,
          "${local.sfn_log_group_arn}:log-stream:*",
        ]
      },

      # --- PR-022 Gold layer ---
      # Invoke the gold-purge Lambda (one call per gold table in the BuildGold Map).
      {
        Sid : "AllowInvokeGoldPurgeLambda",
        Effect : "Allow",
        Action : [
          "lambda:InvokeFunction"
        ],
        Resource : local.gold_purge_lambda_arn
      },
      # Run the CTAS via Athena (.sync polls GetQueryExecution until done).
      {
        Sid : "AllowGoldCtasAthena",
        Effect : "Allow",
        Action : [
          "athena:StartQueryExecution",
          "athena:StopQueryExecution",
          "athena:GetQueryExecution",
          "athena:GetQueryResults"
        ],
        Resource : local.athena_workgroup_arn
      },
      # Athena CTAS creates/replaces the gold tables in the Glue catalog. The purge Lambda
      # already dropped them; these let Athena register the fresh table + partitions.
      {
        Sid : "AllowGoldCatalogWrites",
        Effect : "Allow",
        Action : [
          "glue:GetDatabase",
          "glue:GetTable",
          "glue:GetTables",
          "glue:CreateTable",
          "glue:UpdateTable",
          "glue:DeleteTable",
          "glue:GetPartition",
          "glue:GetPartitions",
          "glue:BatchCreatePartition",
          "glue:CreatePartition",
          "glue:UpdatePartition"
        ],
        Resource : [
          local.glue_catalog_arn,
          local.glue_database_arn,
          local.glue_tables_arn
        ]
      },
      # Lake Formation credential vending. silver/ IS registered with Lake Formation
      # (see the lake-formation module), so Athena does not read those Parquet files with
      # this role's own S3 rights — it asks LF to vend scoped temporary credentials, which
      # requires lakeformation:GetDataAccess on the caller's identity policy. Without it
      # every gold CTAS dies with:
      #   AccessDeniedException: ... not authorized to perform: lakeformation:GetDataAccess
      #   on resource: .../table/lottery_santalucia_db/silver_premios_premios
      # even with the LF SELECT grant in place — under LF BOTH halves are required, the
      # LF grant (who may read) and this IAM action (may this principal ask LF at all).
      #
      # Resource must be "*": Lake Formation actions support no resource types in IAM, so
      # the table-level scoping lives entirely in the LF grants, not here.
      {
        Sid : "AllowGoldLakeFormationDataAccess",
        Effect : "Allow",
        Action : [
          "lakeformation:GetDataAccess"
        ],
        Resource : "*"
      },
      # Athena runs as this role: read silver + the uploaded SQL, write gold Parquet, and
      # read/write its own query metadata under the results bucket.
      #
      # The multipart actions are not optional padding: Athena writes CTAS output (and its
      # result manifest) with multipart uploads and needs to list/abort its own parts, so
      # omitting them fails the write rather than the read. The PR-002 bucket Deny only
      # covers s3:DeleteObject*/DeleteBucket, so none of these are denied for this role.
      {
        Sid : "AllowGoldDataS3",
        Effect : "Allow",
        Action : [
          "s3:GetObject",
          "s3:PutObject",
          "s3:ListBucket",
          "s3:GetBucketLocation",
          "s3:ListBucketMultipartUploads",
          "s3:ListMultipartUploadParts",
          "s3:AbortMultipartUpload"
        ],
        Resource : [
          var.partitioned_bucket_arn,
          "${var.partitioned_bucket_arn}/*",
          "arn:aws:s3:::${var.athena_results_bucket_name}",
          "arn:aws:s3:::${var.athena_results_bucket_name}/*"
        ]
      }
    ]
  })
}

# EventBridge -> Step Function policy
resource "aws_iam_policy" "eventbridge_to_sfn_policy" {
  name = "eventbridge-to-sfn-policy-${var.environment}"

  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Sid : "AllowStartExecutionOfStateMachine",
        Effect : "Allow",
        Action : "states:StartExecution",
        Resource : local.state_machine_arn
      }
    ]
  })
}

# ===========================================================================
# ATTACHMENTS
# ===========================================================================

# Lambda
resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "lambda_custom_attach" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = aws_iam_policy.lambda_custom.arn
}

# Glue job
resource "aws_iam_role_policy_attachment" "glue_attach_policy" {
  role       = aws_iam_role.glue_job_role.name
  policy_arn = aws_iam_policy.glue_job_policy.arn
}

# Glue crawler
resource "aws_iam_role_policy_attachment" "attach_glue_s3" {
  role       = aws_iam_role.glue_crawler_role.name
  policy_arn = aws_iam_policy.glue_crawler_s3_policy.arn
}

# SageMaker
resource "aws_iam_role_policy_attachment" "sagemaker_s3_read_attach" {
  role       = aws_iam_role.sagemaker_execution_role.name
  policy_arn = aws_iam_policy.sagemaker_s3_read_policy.arn
}

resource "aws_iam_role_policy_attachment" "sagemaker_admin_policy_attach" {
  role       = aws_iam_role.sagemaker_execution_role.name
  policy_arn = aws_iam_policy.sagemaker_studio_admin_policy.arn
}

resource "aws_iam_role_policy_attachment" "sagemaker_full_access" {
  role       = aws_iam_role.sagemaker_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSageMakerFullAccess"
}

resource "aws_iam_role_policy_attachment" "cloudwatch_logs_full_access" {
  role       = aws_iam_role.sagemaker_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchLogsFullAccess"
}

# Step Function + EventBridge
resource "aws_iam_role_policy_attachment" "sfn_execution_policy_attachment" {
  role       = aws_iam_role.sfn_execution_role.name
  policy_arn = aws_iam_policy.sfn_execution_policy.arn
}

resource "aws_iam_role_policy_attachment" "eventbridge_to_sfn_policy_attachment" {
  role       = aws_iam_role.eventbridge_to_sfn_role.name
  policy_arn = aws_iam_policy.eventbridge_to_sfn_policy.arn
}

# Gold-purge Lambda (PR-022): CloudWatch Logs basics + the scoped S3/Glue policy.
resource "aws_iam_role_policy_attachment" "gold_purge_basic" {
  role       = aws_iam_role.gold_purge_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "gold_purge_custom" {
  role       = aws_iam_role.gold_purge_lambda.name
  policy_arn = aws_iam_policy.gold_purge_lambda_policy.arn
}

# ---------------------------------------------------------------------------
# PERSONAL IAM-USER GRANTS (opt-in)
#
# PR-009: the two hard-coded attachments (santa-lucia-dev, angel-adming) are now gated
# behind var.personal_iam_users. Empty (the default, and what a fresh cloner gets) => no
# attachments are created. The owner sets the list in a gitignored tfvars to keep their
# own users' Athena-results access.
# ---------------------------------------------------------------------------
resource "aws_iam_user_policy_attachment" "personal_athena_results" {
  for_each   = toset(var.personal_iam_users)
  user       = each.value
  policy_arn = aws_iam_policy.athena_results_access.arn
}
