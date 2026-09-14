# Module: `etl-glue`

The Glue transform job (bronze -> silver), with the script location parameterized.

**Status:** migrated in **PR-011** from `terraform-lottery/Prod/glue_job.tf` via
cross-state `terraform state rm` (legacy) + `terraform import` (main) — the job was not
recreated. See `docs/runbooks/PR-011-glue-migration.md` for the exact commands.

## Cleanup vs. the legacy config

The old config hard-coded `script_location = "s3://lambda-code-zip-prod/lottery_transformer.zip"`.
The module builds it as `s3://${code_bucket}/${script_key}` — in prod that resolves to the
exact same string, so the migration plan is a no-op, but the module is now portable to any
account/bucket.

## PR-016: script path inside the zip

The job zip now carries the `loteria` package at its root, so `--script-file` is
`loteria/transformer/transformer.py` (was `transformer/transformer.py`). Terraform does
**not** manage the `lottery_transformer.zip` S3 object, so it must be rebuilt and uploaded
by hand *before* applying:

```bash
bash scripts/build_glue_package.sh
aws s3 cp dist/lottery_transformer.zip s3://lambda-code-zip-prod/lottery_transformer.zip
```

See `docs/runbooks/PR-016-src-consolidation.md`.

## PR-017: parameterized secret name

The job now receives the Secrets Manager secret name as the `--LOTERIA_SECRET_NAME`
argument (from the `secret_name` input). Glue delivers job arguments on the command line,
not as env vars, so the zipapp entry point (`scripts/glue_zip_main.py`) copies it into
`os.environ` before importing the transformer — that's where
`loteria.common.aws_secrets.get_secrets()` reads it. Cloning into a new account only needs
the secret name changed in one place (root `var.lottery_secret_name`). Rebuild + reupload
the zip after this change.

## Inputs / outputs

- Inputs: `code_bucket`, `script_key` (default `lottery_transformer.zip`),
  `partitioned_bucket_name`, `simple_bucket_name`, `glue_job_role_arn`, `secret_name`,
  `glue_version` (inert — see below), `python_version` (default `"3.9"`), `environment`.
- Outputs: `glue_job_name`, `glue_job_arn`.

## PR-020: runtime spike — staying on Python Shell 3.9

The roadmap's "Glue 4.0 / Python 3.10 upgrade" is **not achievable for this job**, because
it is a **Python Shell** job (`command.name = "pythonshell"`), not a Spark job:

- Python Shell supports only Python **3.6 or 3.9** (3.6 EOL 2026-03-01). There is no 3.10.
- `glue_version` is **inert** for Python Shell — AWS stores it (the live job reads back
  `"3.0"`) but ignores it at runtime. "Glue 4.0/5.0" are Spark-runtime versions.

So we stay on Python Shell 3.9, the only current runtime. A genuinely newer Python/runtime
would mean migrating the job **type** to Spark (`glueetl`) or Ray — a transformer rewrite,
captured as a deferred item, not a version bump. Full reasoning and the AWS-doc evidence:
`docs/runbooks/PR-020-glue-runtime-spike.md`.

## Log retention (PR-023) — these groups are ACCOUNT-WIDE

Glue gives a Python Shell job **no log group of its own**. Every `pythonshell` job in the
account writes stdout to `/aws-glue/python-jobs/output` and stderr to
`/aws-glue/python-jobs/error`. (`--continuous-log-logGroup`, which *would* give a per-job
group, is Spark-only — the same job-family split as the runtime note above.)

So putting retention on this job's logs means owning two groups shared with any other Glue
workload in the account. That is fine here — this is the account's only Python Shell job —
but it is why `manage_shared_glue_log_groups` (default `true`) exists: set it `false` and
the groups are left untouched. Both already exist in prod and are `terraform import`ed; see
`docs/runbooks/PR-023-log-retention.md`.

Extra inputs: `log_retention_days` (default 30), `manage_shared_glue_log_groups`.
Extra output: `log_group_names`.

## PR-033: a SECOND Glue job — the Silver data-quality gate

This module now holds two jobs that share almost nothing but their service.

| | `lottery_transform` | `silver_dq` |
|---|---|---|
| Type | `pythonshell` | `glueetl` (Spark) |
| Runtime | Python 3.9 | Glue 5.0 / Python 3.11 |
| Artifact | one zip, run as a zipapp | a `.py` script + a lib zip via `--extra-py-files` |
| Role | `glue_job_role` (read/write) | `glue_dq_role` (**read-only**) |
| Log group | account-wide, shared | **its own** |
| Writes data? | yes, Silver | never |

**The second job is Spark only to get a newer interpreter.** `great-expectations` 1.x needs
Python >= 3.10; Python Shell caps at 3.9 (the note above). The script never creates a
`SparkContext` — it runs as a plain Python process on the driver. At `2 × G.1X` once a week
that is a few cents, and it is cheaper than rewriting PR-032's suites against the GX 0.18
API or maintaining a second runtime outside Glue.

Three consequences of the job type, none cosmetic:

- **`script_location` must be a plain `.py`.** Spark jobs are `spark-submit`'ed and do not
  execute a zip as a zipapp, so the `__main__.py`-at-the-zip-root trick used by the
  transformer (`scripts/glue_zip_main.py`) does not apply. Hence two artifacts.
- **`max_capacity` is rejected** alongside `worker_type`/`number_of_workers` for `glueetl`.
  `2 × G.1X` is the documented floor, and the work is single-threaded pandas on the driver,
  so anything above the floor is money for no throughput.
- **A Spark job CAN have a per-job log group** — `--continuous-log-logGroup` is the Spark-only
  argument the PR-023 note above complains about, seen from the other side. It gets one,
  because the job's entire output is a verdict someone reads straight after an alert.

Job bookmarks and metrics are off on purpose. The job reads the **whole** dataset every run
by design: uniqueness of `numero_sorteo` is a property of the dataset, not of a batch (see
`src/loteria/dq/runner.py`), so a bookmark skipping "already processed" files would quietly
turn the strongest expectation in the suite into a no-op.

Build the artifacts with `bash scripts/build_dq_package.sh` and upload **both** — Terraform
does not manage these objects, and a stale lib zip fails at import inside the job rather
than at deploy time. Full procedure: `docs/runbooks/PR-033-dq-gate.md`.

Extra inputs: `dq_job_role_arn`, `dq_script_key`, `dq_lib_key`, `dq_glue_version`,
`great_expectations_version` (**must match `requirements/dq.txt`**), `silver_prefix`,
`dq_timeout_minutes`.
Extra outputs: `dq_job_name`, `dq_job_arn`, `dq_log_group_name`.
