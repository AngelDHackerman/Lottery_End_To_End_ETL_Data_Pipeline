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

## Inputs / outputs

- Inputs: `code_bucket`, `script_key` (default `lottery_transformer.zip`),
  `partitioned_bucket_name`, `simple_bucket_name`, `glue_job_role_arn`,
  `glue_version` (default `"3.0"`), `python_version` (default `"3.9"`), `environment`.
- Outputs: `glue_job_name`, `glue_job_arn`.

## TODO

- **PR-020:** Glue 4.0 / Python 3.10 upgrade spike (bump the version defaults, run the
  job once, keep or revert with the failure log).
