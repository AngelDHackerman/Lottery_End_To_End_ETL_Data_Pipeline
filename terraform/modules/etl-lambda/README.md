# Module: `etl-lambda`

The extractor Lambda function (scrapes loteria.org.gt) and its S3 deployment artifact.

**Status:** migrated in **PR-010** from `terraform-lottery/Prod/lambdas.tf` via cross-state
`terraform state rm` (legacy) + `terraform import` (main) — the function was not recreated.
See `docs/runbooks/PR-010-lambda-migration.md` for the exact commands.

## Deliberate change vs. the legacy config

The function's environment variables now carry bucket **names** (not ARNs) plus
`LOTERIA_SECRET_NAME`. This shows up as one in-place update on first apply. It is safe:
the extractor code currently reads all its config from Secrets Manager
(`src/loteria/common/aws_secrets.py`); PR-017 switches the code to consume these env vars.

**PR-016:** the deployment zip now carries the `loteria` package at its root, so
`handler` is `loteria.extractor.lambda_handler.lambda_handler` (was
`extractor.lambda_handler.lambda_handler`). Rebuild the zip with
`scripts/build_lambda_package.sh` **before** applying — see
`docs/runbooks/PR-016-src-consolidation.md`.

## Inputs / outputs

- Inputs: `lambda_code_bucket`, `lambda_zip_key`, `lambda_zip_path`,
  `lambda_exec_role_arn`, `partitioned_bucket_name`, `simple_bucket_name`,
  `secret_name`, `region`, `environment`.
- Outputs: `extractor_lambda_arn`, `extractor_lambda_name`.

## The local zip

`lambda_zip_path` (root default: `lambda_package.zip` inside `terraform/`, gitignored)
must match the deployed artifact or Terraform will want to re-upload it:

```bash
aws s3 cp s3://lambda-code-zip-prod/lambda_package.zip terraform/lambda_package.zip
```

PR-019 replaces this hand-synced zip with built artifacts (thin code zip + dependency layer).
