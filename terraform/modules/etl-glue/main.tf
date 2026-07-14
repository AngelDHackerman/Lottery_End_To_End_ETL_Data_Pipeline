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
    # NOTE: "--script-file" is inert — Glue never reads it. The job artifact is a zip, and
    # Glue runs it as `python lottery_transformer.zip` (a zipapp), so the real entry point
    # is the __main__.py at the ZIP ROOT, which build_glue_package.sh puts there. Kept
    # only as documentation of where the job's code lives; changing it has no effect.
    "--script-file"        = "loteria/transformer/transformer.py"
    "--PARTITIONED_BUCKET" = var.partitioned_bucket_name
    "--SIMPLE_BUCKET"      = var.simple_bucket_name
    "--RAW_PREFIX"         = "raw/"
    "--PROCESSED_PREFIX"   = "processed/"
    "--job-language"       = "python"
    # PR-017: pass the secret name so the code isn't pinned to a hard-coded default.
    # Glue delivers job arguments on the command line (sys.argv), NOT as env vars, so the
    # zipapp entry point (scripts/glue_zip_main.py) copies this into os.environ as
    # LOTERIA_SECRET_NAME before importing the transformer, which is where
    # loteria.common.aws_secrets.get_secrets() reads it.
    "--LOTERIA_SECRET_NAME" = var.secret_name
  }

  execution_property {
    max_concurrent_runs = 1
  }

  tags = {
    Project     = "Loteria-Santa-Lucia"
    Environment = var.environment
  }
}
