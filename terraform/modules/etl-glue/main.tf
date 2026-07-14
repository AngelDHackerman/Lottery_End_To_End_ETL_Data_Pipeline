# Module: etl-glue
# The Glue transform job (bronze -> silver). Migrated from
# terraform-lottery/Prod/glue_job.tf in PR-011 via cross-state `terraform state rm`
# (legacy) + `terraform import` (here) — the job is NOT recreated. See
# docs/runbooks/PR-011-glue-migration.md.
#
# PR-011's cleanup: the script location is no longer the hard-coded
# "s3://lambda-code-zip-prod/lottery_transformer.zip" — it is built from
# var.code_bucket + var.script_key (same resulting string in prod, so the plan
# stays a no-op).
#
# TODO PR-020: Glue 4.0 / Python 3.10 upgrade spike — bump the `glue_version` /
# `python_version` defaults, run the job once in prod, keep or revert with evidence.

resource "aws_glue_job" "lottery_transform" {
  name         = "lottery-transform-${var.environment}"
  role_arn     = var.glue_job_role_arn
  glue_version = var.glue_version
  max_capacity = 1 # 1 DPU: enough for this job

  command {
    name            = "pythonshell"
    script_location = "s3://${var.code_bucket}/${var.script_key}"
    python_version  = var.python_version
  }

  default_arguments = {
    # PR-016: the zip now carries the `loteria` package at its root, so the script path
    # gains the package prefix. Rebuild + upload lottery_transformer.zip
    # (scripts/build_glue_package.sh) BEFORE applying — see the PR-016 runbook.
    "--script-file"        = "loteria/transformer/transformer.py"
    "--PARTITIONED_BUCKET" = var.partitioned_bucket_name
    "--SIMPLE_BUCKET"      = var.simple_bucket_name
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
