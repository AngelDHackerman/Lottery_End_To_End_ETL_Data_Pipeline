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
    "--RAW_PREFIX"         = "raw/"
    "--job-language"       = "python"

    # PR-041.2 removed --SIMPLE_BUCKET, --PROCESSED_PREFIX and --ENABLE_SIMPLE_BUCKET_WRITES.
    # --PROCESSED_PREFIX was the most misleading of the three: it was named after the legacy
    # `processed/` prefix the idempotency check moved off in PR-016, but what it actually
    # addressed was the flat copies in the simple bucket. Nothing consumes any of them now;
    # getResolvedOptions only reads the names the job asks for, so removing them here and
    # uploading the new zip can happen in either order.
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
# PR-033 — the Silver data-quality gate job
# =======================================================================================
#
# WHY THIS IS A SPARK (`glueetl`) JOB AND THE TRANSFORM JOB ABOVE IS NOT.
#
# The roadmap asked for "a Python Shell job that pip-installs great-expectations". That
# cannot work, and PR-032 proved it before this PR started: great-expectations 1.x declares
# `requires-python >=3.10`, and Python Shell offers only 3.6 and 3.9 (PR-020's spike, and
# the module note at the top of this file). On 3.9 pip silently resolves back to the GX 0.18
# line, whose API is unrelated to the one `loteria.dq` is written against — it installs
# cleanly and then fails at import, inside the job, on a Thursday.
#
# So this job exists only to get a newer interpreter. Glue 5.0 is Python 3.11. The script
# never creates a SparkContext; it runs as a plain Python process on the driver. We are
# paying for a Spark cluster to get an interpreter version, which is worth stating plainly
# rather than discovering later: at one run a week on the smallest legal configuration it is
# a few cents, and it is the cheapest of the three options (the others being to rewrite the
# suites against GX 0.18, or to move the gate off Glue entirely onto Lambda/Fargate, which
# buys a second runtime to maintain).
#
# Consequences of the job type that are NOT cosmetic:
#   - `script_location` must be a .py file, not a zip. Spark jobs are spark-submit'ed; they
#     do not run a zip as a zipapp the way pythonshell does, so the `__main__.py`-at-the-root
#     trick from scripts/glue_zip_main.py does not apply here. Our own package arrives
#     separately via `--extra-py-files`.
#   - `max_capacity` is not allowed alongside worker_type/number_of_workers for glueetl —
#     the capacity model is workers, and 2 x G.1X is the documented minimum.
#   - Unlike pythonshell, a Spark job CAN have its own log group via continuous logging, so
#     this one does (see below) instead of sharing the account-wide groups.

# Per-job log group, which the transform job cannot have.
#
# A dedicated group matters more here than elsewhere: the whole output of this job is a
# verdict someone reads after an alert, and hunting for it inside the account-wide
# /aws-glue/jobs/output — shared with every run of the transformer, and in this account with
# another project's workload — is the difference between a 10-second and a 10-minute
# incident response.
#
# ⚠️ PR-033.1: `--continuous-log-logGroup` alone does NOT fill this group. The first real
# run (2026-09-16) left it with zero streams while every line landed in the account-wide
# /aws-glue/jobs/output. Continuous logging ships SPARK's log4j output, and this job
# deliberately never creates a SparkContext — so there is nothing for it to carry, and
# JobRun.LogGroupName reports the base /aws-glue/jobs rather than the group named below.
# The group is therefore written to directly by the job, via --DQ_LOG_GROUP below and
# loteria.common.cloudwatch_logging. The continuous-logging arguments are kept because they
# cost nothing and would start working the day this job ever touches Spark, but they are
# not what makes the group non-empty.
resource "aws_cloudwatch_log_group" "silver_dq" {
  count = var.enable_silver_dq ? 1 : 0

  name              = "/aws-glue/jobs/loteria-silver-dq-${var.environment}"
  retention_in_days = var.log_retention_days

  tags = {
    Project     = "Loteria-Santa-Lucia"
    Environment = var.environment
  }
}

resource "aws_glue_job" "silver_dq" {
  # Gated so the stack is deployable BEFORE `make build` has produced and uploaded the two
  # job artifacts. Without this, a fresh clone must either upload artifacts it has not built
  # yet or apply a job whose script_location points at a key that does not exist — Glue
  # accepts the second quietly and fails at the first run, which is the worse of the two.
  count = var.enable_silver_dq ? 1 : 0

  name     = "loteria-silver-dq-${var.environment}"
  role_arn = var.dq_job_role_arn

  # Real, not inert: for glueetl this selects the runtime (5.0 => Python 3.11, Spark 3.5).
  glue_version = var.dq_glue_version

  # The documented floor for a Spark job. The work is single-threaded pandas on the driver —
  # the workers do nothing — so anything above the minimum is money for no throughput.
  worker_type       = "G.1X"
  number_of_workers = 2

  # A DQ run that hangs must not bill for hours. The validation itself is seconds — but see
  # var.dq_timeout_minutes: almost all of this budget is spent before the script runs at all.
  timeout = var.dq_timeout_minutes

  command {
    name            = "glueetl"
    script_location = "s3://${var.code_bucket}/${var.dq_script_key}"
    python_version  = "3"
  }

  default_arguments = {
    # Our own code. Unlike the transformer's zipapp, this zip is a library on sys.path — the
    # entry point is the script above, which imports from it.
    "--extra-py-files" = "s3://${var.code_bucket}/${var.dq_lib_key}"

    # great-expectations is pip-installed at job start rather than vendored into the zip,
    # because it has compiled transitive dependencies that must be resolved for the job's
    # interpreter, not for whatever machine ran the build script. pandas and pyarrow are
    # deliberately NOT listed: Glue 5.0 already ships them, and pinning them here would
    # fight the runtime's own versions — the same reasoning as requirements/dq.txt, which
    # is where the pin below comes from and must stay in sync with.
    "--additional-python-modules" = "great-expectations==${var.great_expectations_version}"

    "--PARTITIONED_BUCKET" = var.partitioned_bucket_name
    "--SILVER_PREFIX"      = var.silver_prefix

    # Per-job logging. See the log group above for why BOTH of these exist: the two
    # continuous-logging arguments are Spark's mechanism and produce nothing for this job,
    # while --DQ_LOG_GROUP is what the entry point reads to write to the group itself.
    # Terraform stays the single source of the group's name either way.
    "--enable-continuous-cloudwatch-log" = "true"
    "--continuous-log-logGroup"          = aws_cloudwatch_log_group.silver_dq[0].name
    "--DQ_LOG_GROUP"                     = aws_cloudwatch_log_group.silver_dq[0].name

    # Off on purpose. The Spark UI writes event logs to S3, which would mean granting this
    # job's otherwise read-only role a PutObject it has no other use for — and there is no
    # Spark job to inspect, because nothing here runs on Spark.
    "--enable-spark-ui" = "false"

    # Metrics and bookmarks are off for the same reason: this job reads the whole dataset
    # every run by design (uniqueness is a property of the dataset, not of a batch — see
    # loteria/dq/runner.py), so a bookmark that skipped "already processed" files would
    # silently turn the strongest expectation in the suite into a no-op.
    "--enable-metrics"      = "false"
    "--job-bookmark-option" = "job-bookmark-disable"

    "--job-language" = "python"
  }

  # One at a time. Two concurrent validations of the same immutable layer would return the
  # same verdict and bill twice.
  execution_property {
    max_concurrent_runs = 1
  }

  tags = {
    Project     = "Loteria-Santa-Lucia"
    Environment = var.environment
  }
}
