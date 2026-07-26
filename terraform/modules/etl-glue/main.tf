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
# PR-020 (Glue runtime spike) — CONCLUSION: stay on Python Shell 3.9. The roadmap's
# target of "Glue 4.0 / Python 3.10" is not reachable for this job type:
#   - Python Shell supports ONLY Python 3.6 or 3.9 (3.6 EOL 2026-03-01), so there is no
#     3.10 to move to; 3.9 is the sole current runtime.
#   - `glue_version` is INERT for Python Shell — AWS stores the value (this job reads back
#     "3.0") but ignores it at runtime. "Glue 4.0/5.0" are Spark-runtime versions and do
#     not apply here.
# Reaching a newer Python / a "4.0" runtime would require changing the job TYPE from
# pythonshell to a Spark (glueetl) or Ray job — a transformer rewrite, not a version bump.
# Tracked as a deferred item, not PR-020. See docs/runbooks/PR-020-glue-runtime-spike.md.


# --- PR-023: log retention -------------------------------------------------------------
#
# Glue does NOT give a Python Shell job its own log group. Every pythonshell job in the
# account writes stdout to /aws-glue/python-jobs/output and stderr/tracebacks to
# /aws-glue/python-jobs/error, both created by the Glue service on first run with no
# retention. (`--continuous-log-logGroup`, which WOULD give a per-job group, is a Spark-only
# argument — see the runtime note above.) So setting retention means owning those two
# account-wide groups, which is safe here because this job is the account's only Python
# Shell workload — hence the var.manage_shared_glue_log_groups escape hatch.
#
# Both groups already exist in prod and must be IMPORTED, not created:
# see docs/runbooks/PR-023-log-retention.md.
locals {
  shared_log_groups = var.manage_shared_glue_log_groups ? [
    "/aws-glue/python-jobs/output",
    "/aws-glue/python-jobs/error",
  ] : []
}

resource "aws_cloudwatch_log_group" "python_shell" {
  for_each = toset(local.shared_log_groups)

  name              = each.value
  retention_in_days = var.log_retention_days

  # Deliberately untagged: these are Glue service-owned, account-wide groups shared with
  # any future job, so project tags on them would be misleading.
}

resource "aws_glue_job" "lottery_transform" {
  name     = "lottery-transform-${var.environment}"
  role_arn = var.glue_job_role_arn
  # Inert for pythonshell (see the module note above). Kept at the imported value "3.0" so
  # the plan stays a no-op; the real runtime is pinned by command.python_version below.
  glue_version = var.glue_version
  max_capacity = 1 # 1 DPU: enough for this job

  command {
    name            = "pythonshell"
    script_location = "s3://${var.code_bucket}/${var.script_key}"
    python_version  = var.python_version # 3.9 — the only supported Python Shell runtime
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
