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
  # These names are fixed by the Glue service, not chosen by us — so they are stated as
  # constants and exposed as outputs regardless of whether this module MANAGES the groups.
  # PR-024's log widgets need the names to query them; the groups exist in AWS either way.
  glue_output_log_group = "/aws-glue/python-jobs/output" # stdout (the structured JSON logs)
  glue_error_log_group  = "/aws-glue/python-jobs/error"  # stderr + tracebacks

  shared_log_groups = var.manage_shared_glue_log_groups ? [
    local.glue_output_log_group,
    local.glue_error_log_group,
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

# =======================================================================================
# PR-033 — Silver data-quality job (the Gold gate)
# =======================================================================================
# A SECOND Glue job, and deliberately a different job TYPE from the transformer above.
#
# WHY glueetl (Spark) FOR A SCRIPT THAT NEVER TOUCHES SPARK. PR-032 established that
# `great-expectations` 1.x declares `requires-python >=3.10`, while Python Shell supports
# only 3.6 and 3.9 (the spike recorded at the top of this file). The roadmap's "Python Shell
# job that pip-installs great-expectations" therefore cannot work: on 3.9 pip resolves back
# to the GX 0.18 line, whose API is unrelated to the one src/loteria/dq is written against,
# so it would install cleanly and fail at import. Glue 5.0 is where Python 3.11 lives, and
# `glueetl` is the only job type that offers it.
#
# The script never creates a SparkContext, so it runs as an ordinary Python process on the
# driver. The Spark cluster is the price of the interpreter version. At 2 workers, a few
# minutes, once a week, that is cents per year — cheaper than the engineering cost of
# maintaining a second, 0.18-era copy of the suites.
#
# Cost note: unlike the pythonshell transformer (max_capacity = 1 DPU), a Glue 5.0 ETL job
# has a FLOOR of 2 workers. There is no smaller shape available.

locals {
  dq_job_name = "loteria-silver-dq-${var.environment}"

  # Spark jobs, unlike pythonshell ones, CAN have a per-job log group — `--continuous-log-
  # logGroup` is a Spark-only argument (noted in the PR-023 block above, which had to settle
  # for the account-wide groups instead).
  #
  # Taking that option here is not just tidier, it is necessary: the account-wide Spark
  # groups /aws-glue/jobs/{output,error,logs-v2} ALREADY EXIST and already carry another
  # project's Glue Spark workload. The `manage_shared_glue_log_groups` escape hatch above is
  # justified by this being the account's only *pythonshell* job — that reasoning does not
  # extend to Spark, so this module must not claim those groups. It owns a group of its own
  # instead, which Terraform creates fresh with a retention policy.
  dq_log_group = "/aws-glue/jobs/${local.dq_job_name}"
}

resource "aws_cloudwatch_log_group" "silver_dq" {
  count = var.enable_silver_dq ? 1 : 0

  name              = local.dq_log_group
  retention_in_days = var.log_retention_days

  tags = {
    Name        = local.dq_log_group
    Environment = var.environment
    Project     = "Loteria-Santa-Lucia"
  }
}

resource "aws_glue_job" "silver_dq" {
  count = var.enable_silver_dq ? 1 : 0

  name     = local.dq_job_name
  role_arn = var.glue_dq_job_role_arn
  # Real and load-bearing here, unlike on the pythonshell job above where it is inert:
  # "5.0" is what selects Spark 3.5 / Python 3.11.
  glue_version = var.dq_glue_version

  # 2 x G.1X is the minimum shape a Glue 5.0 ETL job accepts. The work is a ~117k-row pandas
  # validation that runs on the driver, so more workers would buy nothing.
  worker_type       = "G.1X"
  number_of_workers = 2

  # Fail fast. The default is 2880 minutes; a DQ run that has not finished in 20 has hung,
  # and the Step Function is waiting on it synchronously.
  timeout = var.dq_timeout_minutes

  command {
    name = "glueetl"
    # A plain .py, NOT a zipapp. glueetl runs the script directly and puts
    # --extra-py-files on sys.path; only pythonshell executes the artifact as `python x.zip`.
    script_location = "s3://${var.code_bucket}/${var.dq_script_key}"
    python_version  = "3"
  }

  default_arguments = {
    # The loteria package. Built by scripts/build_dq_package.sh; Terraform does not manage
    # the object, same as the transformer zip.
    "--extra-py-files" = "s3://${var.code_bucket}/${var.dq_lib_key}"

    # Installed at run time rather than vendored: bundling great-expectations would mean
    # pushing scipy and altair through S3 on every deploy. Pinned to match
    # requirements/dq.txt, which PR-032 verified against the real Silver data.
    #
    # ⚠️ This needs egress to PyPI. The job runs in Glue's managed network (no `connections`
    # block), which has internet access — putting it in the project VPC would break the
    # install unless enable_internet is on, since there is no NAT otherwise.
    "--additional-python-modules" = var.dq_python_modules

    "--PARTITIONED_BUCKET" = var.partitioned_bucket_name
    "--job-language"       = "python"

    # Per-job log group (see the local above). Both arguments are required: the group name
    # alone does nothing unless continuous logging is enabled.
    "--enable-continuous-cloudwatch-log" = "true"
    "--continuous-log-logGroup"          = local.dq_log_group

    # Off deliberately. The Spark UI writes event logs to S3, and this job runs no Spark
    # stages worth inspecting — it would be paying S3 writes for empty event files.
    "--enable-spark-ui" = "false"
  }

  execution_property {
    max_concurrent_runs = 1
  }

  tags = {
    Name        = local.dq_job_name
    Project     = "Loteria-Santa-Lucia"
    Environment = var.environment
  }

  depends_on = [aws_cloudwatch_log_group.silver_dq]
}
