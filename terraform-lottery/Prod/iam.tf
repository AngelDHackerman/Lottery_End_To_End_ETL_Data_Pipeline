# IAM Policies for Lambda, CloudTrail, CloudWatch and StepFuctions

# Policy: SageMaker S3 read-only for parquet files
resource "aws_iam_policy" "sagemaker_s3_read_policy" {
  name        = "lottery-sagemaker-s3-read-policy-${var.environment}"
  description = "Allows SageMaker to read raw and processed data"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow",
        Action    = [
          "s3:GetObject",
          "s3:ListBucket"
        ],
        Resource = [
          var.s3_bucket_simple_data_storage_prod_arn,
          "${var.s3_bucket_simple_data_storage_prod_arn}/*"
        ]
      }
    ]
  })
}

# Policy for Glue Crawler to S3 
resource "aws_iam_policy" "glue_crawler_s3_policy" {
  name            = "glue-crawler-s3-access"
  description     = "Allow Glue crawler to access partitioned lottery bucket"
  policy          = jsonencode({
    Version       = "2012-10-17"
    Statement     = [
      {
        Effect = "Allow",
        Action = [
          "s3:GetObject",
          "s3:ListBucket"
        ],
        Resource = [
          "${var.s3_bucket_partitioned_data_storage_prod_arn}",
          "${var.s3_bucket_partitioned_data_storage_prod_arn}/*",

          "arn:aws:s3:::lottery-athena-results-prod",
          "arn:aws:s3:::lottery-athena-results-prod/*"
        ]
      }
    ]
  })
}

# Policy for access to S3 and Logs for Glue Job
data "aws_iam_policy_document" "glue_job_policy"{
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
      "arn:aws:s3:::${var.s3_bucket_partitioned_name}",
      "arn:aws:s3:::${var.s3_bucket_partitioned_name}/*",
      "arn:aws:s3:::${var.s3_bucket_simple_name}",
      "arn:aws:s3:::${var.s3_bucket_simple_name}/*"
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
    resources = ["*"]
  }

  statement {
    sid    = "AllowSecretsManager"
    effect = "Allow"
    actions = ["secretsmanager:GetSecretValue"]
    resources = ["arn:aws:secretsmanager:*:*:secret:*"]
  }

  statement {
    sid    = "AllowGlueToAccessScriptZip"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:HeadObject"
    ]
    resources = [
      "arn:aws:s3:::lambda-code-zip-prod",
      "arn:aws:s3:::lambda-code-zip-prod/*"
    ]
  }

  statement {
    sid    = "AllowListBucketPartitioned"
    effect = "Allow"
    actions = [
      "s3:ListBucket"
    ]
    resources = [
      "arn:aws:s3:::${var.s3_bucket_partitioned_name}"
    ]
  }
}

resource "aws_iam_policy" "glue_job_policy" {
  name   = "glue-lottery-transform-policy-${var.environment}"
  policy = data.aws_iam_policy_document.glue_job_policy.json
}

resource "aws_iam_role_policy_attachment" "glue_attach_policy" {
  role       = aws_iam_role.glue_job_role.name
  policy_arn = aws_iam_policy.glue_job_policy.arn
}

# Policy for Athena Resutls 
resource "aws_iam_policy" "athena_results_access" {
  name              = "athena-results-s3-access"
  policy            = jsonencode({
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
          aws_s3_bucket.athena_results.arn,
          "${aws_s3_bucket.athena_results.arn}/*"
        ]
      }
    ]
  })
}

# Lambda Policy (S3 + Secrets Manager)
data "aws_iam_policy_document" "lambda_custom_doc"{
  statement {
    sid     = "S3Access"
    effect  = "Allow"

    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:ListBucket",
      "s3:HeadObject"
    ]

    resources = [
      "arn:aws:s3:::${var.s3_bucket_partitioned_name}",
      "arn:aws:s3:::${var.s3_bucket_partitioned_name}/*",
      "arn:aws:s3:::${var.s3_bucket_simple_name}",
      "arn:aws:s3:::${var.s3_bucket_simple_name}/*"
    ]
  } 

  statement {
    sid    = "SecretsManagerAccess"
    effect = "Allow"
    actions = [
      "secretsmanager:GetSecretValue",
      "secretsmanager:DescribeSecret"
    ]
    resources = ["*"] # Limit if you want an specific secret
  }
}

resource "aws_iam_policy" "lambda_custom" {
  name   = "lottery-lambda-custom${var.environment}"
  policy = data.aws_iam_policy_document.lambda_custom_doc.json
}

# IAM Role for SageMaker Studio
resource "aws_iam_role" "sagemaker_execution_role" {
  name = "lottery-sagemaker-execution-role-${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement     = [{
      Effect      = "Allow", 
      Principal   = {
        Service   = "sagemaker.amazonaws.com"
      },
      Action    = "sts:AssumeRole"
    }]
  })

  tags = {
    Name = "lottery-sagemaker-role-${var.environment}"
  }
}

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

# Role for AWS Glue Crawler
resource "aws_iam_role" "glue_crawler_role" {
  name = "glue-crawler-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17",
    Statement = [{
      Action      = "sts:AssumeRole",
      Principal   = {
        Service = "glue.amazonaws.com"
      },
      Effect    = "Allow",
      Sid       = ""
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

# Role for Lambdas
resource "aws_iam_role" "lambda_exec" {
  name = "lottery-lambda-exec-role${var.environment}"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect      = "Allow",
      Principal   = { Service = "lambda.amazonaws.com" },
      Action      = "sts:AssumeRole"
    }]
  })
}

# Lambda Basic access for CloudWatch Logs
resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Attach policy to SageMaker execution role
resource "aws_iam_role_policy_attachment" "sagemaker_s3_read_attach" {
  role       = aws_iam_role.sagemaker_execution_role.name
  policy_arn = aws_iam_policy.sagemaker_s3_read_policy.arn
}

resource "aws_iam_role_policy_attachment" "sagemaker_admin_policy_attach" {
  role       = aws_iam_role.sagemaker_execution_role.name
  policy_arn = aws_iam_policy.sagemaker_studio_admin_policy.arn
}

# Attach AWS-managed policies for SageMaker
resource "aws_iam_role_policy_attachment" "sagemaker_full_access" {
  role       = aws_iam_role.sagemaker_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSageMakerFullAccess"
}

resource "aws_iam_role_policy_attachment" "cloudwatch_logs_full_access" {
  role       = aws_iam_role.sagemaker_execution_role.name
  policy_arn = "arn:aws:iam::aws:policy/CloudWatchLogsFullAccess"
}

# Attach policy to AWS Glue Crawler
resource "aws_iam_policy_attachment" "glue_service_policy" {
  name       = "glue-service-policy"
  roles      = [aws_iam_role.glue_crawler_role.name]
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}

resource "aws_iam_role_policy_attachment" "attach_glue_s3" {
  role          = aws_iam_role.glue_crawler_role.name
  policy_arn    = aws_iam_policy.glue_crawler_s3_policy.arn
}

# Attach user santa_lucia_dev for athena results bucket
data "aws_iam_user" "santa_lucia_dev" { user_name = "santa-lucia-dev" }

resource "aws_iam_user_policy_attachment" "attach_results_user_dev" {
  user       = data.aws_iam_user.santa_lucia_dev.user_name
  policy_arn = aws_iam_policy.athena_results_access.arn
}


# Attach user angel_adming for athena results bucket
data "aws_iam_user" "angel_adming" { user_name = "angel-adming" }
resource "aws_iam_user_policy_attachment" "attach_results_user_adming" {
  user        = data.aws_iam_user.angel_adming.user_name
  policy_arn  = aws_iam_policy.athena_results_access.arn
}

# Attachment for lambda roles
resource "aws_iam_role_policy_attachment" "lambda_custom_attach" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = aws_iam_policy.lambda_custom.arn
}

# -----------
# Role for Step Functions
# -----------

# resource "aws_iam_role" "sfn_exec" {
#   name = "lotter-sfn-exec-role-${var.environment}"
#   assume_role_policy = jsonencode({
#     Version = "2012-10-17",
#     Statement = [{
#       Effect    = "Allow",
#       Principal = { Service = "states.amazonaws.com" },
#       Action    = "sts:AssumeRole"
#     }]
#   })
# }

# data "aws_iam_policy_document" "sfn_policy_doc" {
#   statement {
#     sid    = "InvokeLambdas"
#     effect = "Allow"
#     actions = ["lambda:InvokeFunction"]
#     resources = [
#       aws_lambda_function.extractor_lambda.arn,
#       aws_lambda_function.transformer_lambda.arn
#     ]
#   }

#   # Access to write logs of Step Functions
#   statement {
#     sid       = "Logs"
#     effect    = "Allow"
#     actions   = ["logs:*"]
#     resources = ["arn:aws:logs:*:*:*"]
#   }
# }

# resource "aws_iam_policy" "sfn_policy" {
#   name   = "lottery-sfn-policy${var.environment}"
#   policy = data.aws_iam_policy_document.sfn_policy_doc.json
# }

# resource "aws_iam_role_policy_attachment" "sfn_policy_attach" {
#   role       = aws_iam_role.sfn_exec.name
#   policy_arn = aws_iam_policy.sfn_policy.arn
# }