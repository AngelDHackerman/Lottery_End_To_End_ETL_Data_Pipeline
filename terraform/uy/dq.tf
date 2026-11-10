# The silver gate (UY-043.4). DESIGN.md D20, D30; roadmap UY-043.4.
#
# A Glue 5.0 Spark job that never touches Spark: Glue 5.0 is the only Glue runtime with the
# Python 3.11 that great-expectations 1.x needs (Python Shell stops at 3.9, PR-020), so the
# cluster is the price of the interpreter. Same shape as Santa Lucía's loteria-silver-dq job
# (PR-033), with the one thing D30 set out to measure changed: GX arrives as a zip of wheels
# from S3, installed with --no-index, instead of from PyPI at every start (~21 minutes there).
#
# Two artifacts, both uploaded by this stack so the job and what it runs change in one apply:
#   uy/dq/uy_dq_glue_main.py      the script (a Spark job's script_location must be one .py)
#   uy/dq/uy_dq.gluewheels.zip    GX and what Glue 5.0 lacks + the sorteos wheel (UY-026.2)
# The zip must exist before `terraform plan`, which hashes it; `make uy-tf-plan` builds it.
#
# No log group here. Continuous logging ships Spark's log4j output and this job has none, so a
# per-job group would stay empty (master's PR-033.1). The job's lines land in the account-wide
# /aws-glue/jobs/output, in the stream named after the run id; `make uy-dq-run` reads them.

locals {
  dq_job_name   = "lottery-uy-silver-dq-${var.environment}"
  dq_script_key = "${local.artifacts_prefix}dq/uy_dq_glue_main.py"
  # Glue recognises a zip of wheels by this suffix.
  dq_zip_key = "${local.artifacts_prefix}dq/uy_dq.gluewheels.zip"
}

resource "aws_s3_object" "dq_script" {
  bucket      = data.aws_s3_bucket.code.bucket
  key         = local.dq_script_key
  source      = "${path.module}/../../scripts/uy_dq_glue_main.py"
  source_hash = filemd5("${path.module}/../../scripts/uy_dq_glue_main.py")
}

# source_hash, not etag: at ~49 MB the upload is multipart, and a multipart ETag is not the
# file's MD5, so `etag` would plan a change on every run.
resource "aws_s3_object" "dq_zip" {
  bucket      = data.aws_s3_bucket.code.bucket
  key         = local.dq_zip_key
  source      = var.dq_zip_path
  source_hash = filemd5(var.dq_zip_path)
}

resource "aws_glue_job" "silver_dq" {
  #checkov:skip=CKV_AWS_195:a security configuration encrypts what a job writes (S3 output, bookmarks, logs); this one writes nothing to S3, keeps no bookmark and logs counts, never data
  name     = local.dq_job_name
  role_arn = aws_iam_role.dq_glue.arn

  glue_version = "5.0" # Python 3.11; requirements/glue-5.0-base.txt is tied to it

  # The floor for a Spark job. The work is pandas on the driver; the second worker is idle.
  worker_type       = "G.1X"
  number_of_workers = 2

  # Minutes. The validation is seconds; this bounds a start-up gone wrong. It also has to fit
  # the state machine's hour after fetch and silver (pipeline.tf, execution_timeout_seconds).
  timeout = var.dq_timeout_minutes

  command {
    name            = "glueetl"
    script_location = "s3://${aws_s3_object.dq_script.bucket}/${aws_s3_object.dq_script.key}"
    python_version  = "3"
  }

  default_arguments = {
    # P14: pip installs from the zip alone and never reaches PyPI. What Glue 5.0 already has
    # (pandas, numpy, pyarrow) is not in the zip and is not reinstalled.
    "--additional-python-modules"       = "s3://${aws_s3_object.dq_zip.bucket}/${aws_s3_object.dq_zip.key}"
    "--python-modules-installer-option" = "--no-index"

    "--SILVER_BUCKET" = data.aws_s3_bucket.partitioned.bucket
    "--SILVER_PREFIX" = local.silver_prefix

    # All off: there is no Spark job to inspect, the role cannot write to S3 (the Spark UI
    # would need it), and a bookmark would turn "validate all of silver" into "validate
    # nothing new" (uniqueness is a property of the whole table).
    "--enable-spark-ui"     = "false"
    "--enable-metrics"      = "false"
    "--job-bookmark-option" = "job-bookmark-disable"
    "--job-language"        = "python"
  }

  # One at a time: two validations of the same silver give the same verdict and bill twice.
  # A hand-started run that overlaps the nightly one fails that night's ValidateSilver, so
  # `make uy-dq-run` is not for 23:30 Montevideo.
  execution_property {
    max_concurrent_runs = 1
  }
}
