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
  `glue_version` (default `"3.0"`), `python_version` (default `"3.9"`), `environment`.
- Outputs: `glue_job_name`, `glue_job_arn`.

## TODO

- **PR-020:** Glue 4.0 / Python 3.10 upgrade spike (bump the version defaults, run the
  job once, keep or revert with the failure log).
