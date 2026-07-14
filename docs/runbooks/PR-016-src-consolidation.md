# PR-016 — Single source of truth: `src/loteria/`

Consolidates the two parallel code trees (`lambda/` and `glue_job_transformer/`) into one
Python package, `src/loteria/`, and deletes the stale scratch tree `modules/ETL/Prod/`.

The code itself is unchanged — this is moves + import-path edits + deletions. But the
**deployment artifacts change shape**, and two Terraform values are coupled to that shape.
Read the "Deploy order" section before applying, or the weekly run will break.

## What moved

| Was | Now | Why |
|---|---|---|
| `lambda/extractor/{aws_secrets,s3_utils}.py` | `src/loteria/common/` | Shared by the Lambda *and* the Glue job — they were byte-identical copies in both trees. |
| `lambda/extractor/{scraping,lambda_handler}.py` | `src/loteria/extractor/` | The Lambda. |
| `glue_job_transformer/parser/parser.py` | `src/loteria/parser/` | Identical in both trees. |
| `glue_job_transformer/transformer/transformer.py` | `src/loteria/transformer/` | The Glue job's source of truth — the **Silver** version. |
| `glue_job_transformer/__main__.py` | `src/loteria/transformer/__main__.py` | Entry point, now runnable as `python -m loteria.transformer`. |
| `lambda/requirements_extractor.txt` | `requirements/extractor.txt` | |
| `glue_job_transformer/requirements.txt` | `requirements/glue.txt` | |
| `build_lambda_package.sh` | `scripts/build_lambda_package.sh` | |

**Deleted:**

- `lambda/transformer/` — dead code. The transform runs on Glue, not Lambda
  (`challanges_faced.md` §7). Its `transformer.py` was the *old* version that wrote to
  `processed/`; the surviving Glue one writes `silver/`.
- `lambda/extractor/dry_test.py` — scratch.
- `modules/ETL/Prod/` — stale scratch. `extract.py` was a gutted Selenium-era stub with
  its function bodies already deleted; `hacker_rank.py` was a coding puzzle; the parquet
  viewers read `./temp_files/`, which PR-001 removed.

Imports were rewritten mechanically: `extractor.aws_secrets` / `extractor.s3_utils` →
`loteria.common.*`, `parser.parser` → `loteria.parser.parser`, and so on.

## The coupling: zip layout ↔ Terraform

Both artifacts now carry the `loteria` package at the **zip root** (they used to carry
bare `extractor/` / `transformer/` / `parser/` dirs). So two Terraform values changed:

| Where | Was | Now |
|---|---|---|
| `modules/etl-lambda` `handler` | `extractor.lambda_handler.lambda_handler` | `loteria.extractor.lambda_handler.lambda_handler` |
| `modules/etl-glue` `--script-file` | `transformer/transformer.py` | `loteria/transformer/transformer.py` |

**A new handler against an old zip is a guaranteed `Runtime.ImportModuleError`.** The zips
must be rebuilt first.

## Deploy order

The Lambda zip and the Glue zip differ in one important way: Terraform manages the Lambda
artifact (`aws_s3_object.lambda_package`, sourced from `lambda_zip_path`), so `apply`
uploads it and flips the handler together. **Terraform does not manage the Glue zip** —
that upload is manual.

```bash
# 1. Rebuild both artifacts from src/loteria/
make build
#    -> terraform/lambda_package.zip   (deps + loteria/ at the root)
#    -> dist/lottery_transformer.zip   (loteria/ at the root, code only)

# 2. Upload the Glue zip yourself — Terraform will not do this for you.
aws s3 cp dist/lottery_transformer.zip s3://lambda-code-zip-prod/lottery_transformer.zip

# 3. Now apply. This uploads the new Lambda zip and switches both paths.
cd terraform && terraform plan     # expect: 1 update to the s3 object + 1 to the function
terraform apply
```

Expected plan: an in-place update of `aws_lambda_function.extractor_lambda` (handler +
`source_code_hash`), an update of `aws_s3_object.lambda_package` (etag), and an in-place
update of `aws_glue_job.lottery_transform` (`--script-file`). No destroys.

## Smoke test

```bash
# Lambda — must return {"status": "ok", ...}, not an import error
aws lambda invoke --function-name lottery-extractor-prod \
  --payload '{"lottery_number": null}' /dev/stdout

# Glue — the transform reads raw/ and writes silver/
aws glue start-job-run --job-name lottery-transform-prod
aws glue get-job-run --job-name lottery-transform-prod --run-id <id> \
  --query 'JobRun.JobRunState'
```

If the Lambda fails with `Unable to import module 'loteria/extractor/lambda_handler'`, the
deployed zip is the old one — re-run step 1 and re-apply.

## Rollback

Revert the two Terraform path values and re-upload the previous zips. Nothing is
destroyed by this PR, and no data is touched.

## Known follow-ups (not fixed here — out of scope by design)

- `scraping.py` and `transformer.py` still call `get_secrets()` **at import time**, so
  importing them reaches out to AWS. That is what makes them awkward to unit-test.
  **PR-017** parameterizes the config; **PR-029/030** add the tests that need it.
- `transformer.py` imports `awsglue.utils` at module top, which only exists inside Glue.
- `ruff check` still reports pre-existing lint errors in the moved code (bare `except:`,
  unused imports). Left alone deliberately — this PR is a move, and fixing them would
  bury it. They land with the lint gate in **PR-034**.
