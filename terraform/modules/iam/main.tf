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

  # PR-033: the Silver DQ Glue job and the SNS alerts topic.
  #
  # Both are built from their names for the SAME reason as sfn_log_group_arn above — keeping
  # the dependency direction one-way. The topic is the sharper case: module.observability
  # OWNS the topic but also CONSUMES module.orchestration (the dashboard and alarms name the
  # state machine, the gold-purge Lambda and the weekly rule). So orchestration cannot take
  # observability's output without a module cycle, and neither can this module. Constructing
  # the ARN is the standard way out.
  #
  # The cost is a name that now appears in two places. If the topic is ever renamed in
  # modules/observability/main.tf, this line and modules/orchestration must move with it —
  # a plan will NOT catch it, because both sides are valid strings. Stated here so the
  # coupling is visible from the side most likely to be read first.
  dq_job_arn       = "arn:aws:glue:${var.aws_region}:${local.account_id}:job/${var.dq_glue_job_name}"
  alerts_topic_arn = "arn:aws:sns:${var.aws_region}:${local.account_id}:loteria-alerts-${var.environment}"

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
# PR-033: a SEPARATE, READ-ONLY role for the Silver DQ job.
#
# It would have been one line to reuse glue_job_role. That role carries s3:PutObject and
# s3:DeleteObject on BOTH data buckets, because the transformer writes Silver. A validator
# holding those permissions is not a gate: a bug — or anything that ever runs inside that
# job — could modify the very data it is asserting about, and the green verdict would still
# be green. The whole value of this PR is that something independent says "Silver is fine",
# so the thing saying it must not be able to change Silver.
#
# Reuses the same assume-role document: the principal is still glue.amazonaws.com.
resource "aws_iam_role" "glue_dq_role" {
  name               = "glue-silver-dq-role-${var.environment}"
  assume_role_policy = data.aws_iam_policy_document.glue_assume_role_policy.json

  tags = {
    Project     = "Loteria-Santa-Lucia"
    Environment = var.environment
  }
}

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

# Role for the S3 object-count emitter (PR-027). Read-only by construction: it may LIST
# the data bucket and publish metrics, nothing else. Kept separate from the gold-purge role
# specifically so an observability component can never acquire a Delete.
resource "aws_iam_role" "object_count_lambda" {
  name = "lottery-object-count-role-${var.environment}"

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

# SageMaker S3 read-only over the Silver and Gold layers.
#
# PR-041.2 REPOINTED this policy. Until here its entire content was GetObject + ListBucket
# on the simple bucket and nothing else — so the one consumer this architecture ever
# contemplated (a notebook) was granted read on exactly the bucket PR-041.3 destroys, and
# on nothing that survives it. Stripping the write grants without fixing this would have
# left a SageMaker role whose only data permission points at a bucket that stops existing.
#
# Silver and Gold, not raw/: a notebook wants the typed Parquet, and raw/ is the
# transformer's input, not an analysis surface. Reading these through Athena additionally
# needs a Lake Formation grant — this policy covers the direct S3 read (pandas.read_parquet
# and friends), which is what the simple bucket's flat files were for.
resource "aws_iam_policy" "sagemaker_s3_read_policy" {
  name        = "lottery-sagemaker-s3-read-policy-${var.environment}"
  description = "Allows SageMaker to read the Silver and Gold layers of the partitioned bucket"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ReadSilverAndGoldObjects",
        Effect = "Allow",
        Action = ["s3:GetObject"],
        Resource = [
          "${var.partitioned_bucket_arn}/silver/*",
          "${var.partitioned_bucket_arn}/gold/*"
        ]
      },
      {
        # ListBucket is bucket-level, so the resource must be the bucket itself; the
        # s3:prefix condition is what keeps it from being a licence to enumerate raw/.
        # A list with no prefix sends no s3:prefix key and is therefore denied — that is
        # deliberate, not an oversight.
        Sid      = "ListSilverAndGoldOnly",
        Effect   = "Allow",
        Action   = ["s3:ListBucket"],
        Resource = [var.partitioned_bucket_arn],
        Condition = {
          StringLike = {
            "s3:prefix" = ["silver/*", "gold/*"]
          }
        }
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
    # PR-041.2: the simple bucket's ARNs were here too, for the transformer's flat copies.
    # The code that wrote them is gone, so the grant is now permission to do nothing.
    resources = [
      var.partitioned_bucket_arn,
      "${var.partitioned_bucket_arn}/*"
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

# PR-033: the DQ job's policy. Every statement is read-only by construction — there is no
# s3:PutObject, no s3:DeleteObject and no secretsmanager grant anywhere below, and that is
# the point rather than an oversight.
data "aws_iam_policy_document" "glue_dq_policy" {
  statement {
    sid    = "AllowReadSilverLayer"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:ListBucket",
    ]
    # ListBucket is a BUCKET-level action and GetObject an OBJECT-level one, so both ARNs
    # are needed. The object grant is narrowed to the Silver prefix; the bucket grant cannot
    # be narrowed the same way (the prefix restriction for ListBucket is a condition on
    # s3:prefix, deliberately not used here — the runner lists with a prefix already, and a
    # condition that silently returns an empty page would surface as SilverDatasetEmpty,
    # i.e. as "the transformer never ran", which is the misdiagnosis that class of error is
    # hardest to recover from).
    resources = [
      var.partitioned_bucket_arn,
      "${var.partitioned_bucket_arn}/${var.silver_prefix}*",
    ]
  }

  statement {
    sid    = "AllowReadJobArtifacts"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:ListBucket",
    ]
    # The entry-point script and the --extra-py-files zip.
    resources = [
      "arn:aws:s3:::${var.lambda_code_bucket_name}",
      "arn:aws:s3:::${var.lambda_code_bucket_name}/*",
    ]
  }

  statement {
    sid    = "AllowCloudWatchLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogGroup",
      "logs:CreateLogStream",
      "logs:PutLogEvents",
      # Spark continuous logging associates the stream with the group it was told to use.
      "logs:AssociateKmsKey",
    ]
    # A Spark job writes under /aws-glue/jobs/* (the account-wide output/error groups) AND
    # to the per-job continuous-log group this stack creates. Same reasoning as the transform
    # role: the whole /aws-glue/ prefix, because Glue picks the group by job type.
    resources = [
      "arn:aws:logs:${var.aws_region}:${local.account_id}:log-group:/aws-glue/*",
      "arn:aws:logs:${var.aws_region}:${local.account_id}:log-group:/aws-glue/*:log-stream:*",
    ]
  }
}

resource "aws_iam_policy" "glue_dq_policy" {
  name   = "glue-silver-dq-policy-${var.environment}"
  policy = data.aws_iam_policy_document.glue_dq_policy.json
}

resource "aws_iam_role_policy_attachment" "glue_dq_attach_policy" {
  role       = aws_iam_role.glue_dq_role.name
  policy_arn = aws_iam_policy.glue_dq_policy.arn
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

    # PR-041.2: dropped the simple bucket, whose only use here was the extractor's third
    # write (the flat raw/sorteo_<N>.txt), removed in the same PR.
    resources = [
      var.partitioned_bucket_arn,
      "${var.partitioned_bucket_arn}/*"
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
# PR-027: the object-count emitter. Two grants, both minimal.
#
# `s3:ListBucket` is on the BUCKET arn, not `bucket/*` — listing is a bucket-level action,
# and the object-level arn would grant nothing. Note there is deliberately no `s3:GetObject`
# here: counting and sizing come entirely from the ListObjectsV2 response, so this role can
# see that objects exist and how big they are, and can never read what is in them.
resource "aws_iam_policy" "object_count_lambda_policy" {
  name = "lottery-object-count-policy-${var.environment}"

  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Sid      = "ListMedallionPrefixes",
        Effect   = "Allow",
        Action   = ["s3:ListBucket"],
        Resource = var.partitioned_bucket_arn
      },
      {
        # Same shape as the extractor's grant (PR-026): cloudwatch:PutMetricData supports no
        # resource-level permissions, so `Resource` must be "*" and the real scope is the
        # `cloudwatch:namespace` condition. A namespace mismatch between this condition and
        # the Lambda's METRICS_NAMESPACE env var denies every publish SILENTLY — Terraform
        # passes the same variable to both, which is what keeps them honest.
        Sid      = "PublishLayerMetrics",
        Effect   = "Allow",
        Action   = ["cloudwatch:PutMetricData"],
        Resource = "*",
        Condition = {
          StringEquals = {
            "cloudwatch:namespace" = var.metrics_namespace
          }
        }
      }
    ]
  })
}

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
        # PR-042.1: the Lambda no longer drops the PUBLISHED table — it builds a staging
        # table beside it and swaps the catalog onto it with UpdateTable. That needs the
        # write side of the catalog for tables and their partitions.
        #
        # DeleteTable stays, and is now used only against the staging entry (and against a
        # leftover staging entry from a failed attempt of the same execution). It is kept
        # rather than narrowed because Glue resource ARNs cannot express "tables whose name
        # ends in __stg_*" — the wildcard is per-table-name, not a suffix match.
        Sid    = "SwapGoldTable",
        Effect = "Allow",
        Action = [
          "glue:GetTable",
          "glue:CreateTable",
          "glue:UpdateTable",
          "glue:DeleteTable",
          "glue:GetPartition",
          "glue:GetPartitions",
          # PR-042.4: the Batch* actions are NOT what Glue authorises the Batch* APIs
          # against. batch_update_partition is checked per item, against the SINGULAR
          # glue:UpdatePartition — the denial said so in as many words:
          #
          #   not authorized to perform: glue:UpdatePartition on resource:
          #   arn:aws:glue:us-east-1:913524903233:catalog
          #
          # while the policy already listed glue:BatchUpdatePartition. The singular form is
          # the one that grants; the Batch* names are kept because Glue's own docs list
          # them and removing them on this evidence would be guessing in the other
          # direction. The SFN policy below has carried the singular pair since PR-009,
          # which is why the CTAS path never hit this.
          "glue:BatchCreatePartition",
          "glue:BatchUpdatePartition",
          "glue:BatchDeletePartition",
          "glue:CreatePartition",
          "glue:UpdatePartition",
          "glue:DeletePartition"
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
        # PR-009 narrowed this from "*" to the one transform job; PR-033 adds the DQ job.
        # Still a list of exactly the jobs this pipeline starts, not a wildcard.
        Resource : [local.glue_job_arn, local.dq_job_arn]
      },
      # PR-033: the DQ gate's Catch handler publishes the failure detail before the execution
      # fails. Worth the extra grant rather than leaning on PR-025's sfn_execution_failed
      # alarm: that alarm fires on ANY failed execution and its message is "an execution
      # failed", while this one carries the suite, the expectation and the column — which is
      # usually enough to tell a site change from a parser bug without opening the console.
      {
        Sid : "AllowPublishDQFailureAlert",
        Effect : "Allow",
        Action : ["sns:Publish"],
        Resource : local.alerts_topic_arn
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

# Object-count emitter (PR-027): CloudWatch Logs basics + the read-only list/publish policy.
resource "aws_iam_role_policy_attachment" "object_count_basic" {
  role       = aws_iam_role.object_count_lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "object_count_custom" {
  role       = aws_iam_role.object_count_lambda.name
  policy_arn = aws_iam_policy.object_count_lambda_policy.arn
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
