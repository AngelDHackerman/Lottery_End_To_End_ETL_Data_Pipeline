resource "aws_glue_job" "lottery_transform" {
  name              = "lottery-transform-${var.environment}"
  role_arn          = aws_iam_role.glue_job_role.arn
  glue_version      = "3.0"
  max_capacity      = 1     # 1 DPU: enough for this job

  command {
    name            = "pythonshell" # Este es clave: tipo Python Shell
    # script_location = "s3://${var.s3_code_zip}/${var.script_key}" # ZIP ya subido
    script_location = "s3://lambda-code-zip-prod/lottery_transformer.zip"
    python_version  = "3.9"
  }

  default_arguments = {
    "--script-file"       = "transformer/transformer.py"
    "--PARTITIONED_BUCKET" = var.s3_bucket_partitioned_name
    "--SIMPLE_BUCKET"      = var.s3_bucket_simple_name
    "--RAW_PREFIX"         = "raw/"
    "--PROCESSED_PREFIX"   = "processed/"
    "--job-language"       = "python"
  }

  execution_property {
    max_concurrent_runs = 1
  }

  tags = {
    Project     = "Loteria-Santa-Lucia"
    Environment = var.environment
  }
}