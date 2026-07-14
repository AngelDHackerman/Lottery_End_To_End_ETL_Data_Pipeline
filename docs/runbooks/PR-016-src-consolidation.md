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

## The coupling: zip layout ↔ entry points

Both artifacts now carry the `loteria` package at the **zip root** (they used to carry
bare `extractor/` / `transformer/` / `parser/` dirs). The two runtimes find their entry
point in completely different ways, and both are coupled to that root layout.

### Lambda: the `handler` string

`modules/etl-lambda` `handler` moves from `extractor.lambda_handler.lambda_handler` to
`loteria.extractor.lambda_handler.lambda_handler`. **A new handler against an old zip is a
guaranteed `Runtime.ImportModuleError`**, so the zip must be rebuilt before applying —
Terraform manages the artifact, so `apply` uploads it and flips the handler together.

### Glue: `__main__.py` at the zip root — NOT `--script-file`

Glue runs a zip artifact as a **zipapp** (`python lottery_transformer.zip`), so Python
requires a `__main__.py` at the **zip root**. The job's `--script-file` argument is
**inert — Glue never reads it.**

This was only discovered by the PR-016 smoke test failing with:

```
ImportError: can't find '__main__' module in '/tmp/glue-python-scripts-XXXX/lottery_transformer.zip'
```

The pre-PR-016 zip worked purely because `glue_job_transformer/__main__.py` happened to sit
at that tree's root, and so landed at the zip root. Moving it into the package
(`src/loteria/transformer/__main__.py`, for `python -m loteria.transformer`) removed the
zipapp entry point.

So `scripts/glue_zip_main.py` is copied into the zip root as `__main__.py` by
`build_glue_package.sh`. If you ever restructure the Glue zip, **the root `__main__.py` is
the thing that must survive** — updating `--script-file` accomplishes nothing.

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
# Lambda — note --cli-binary-format: AWS CLI v2 base64-decodes --payload without it.
aws lambda invoke --function-name lottery-extractor-prod \
  --cli-binary-format raw-in-base64-out \
  --payload '{"lottery_number": null}' /tmp/out.json && cat /tmp/out.json

# Glue — the transform reads raw/ and writes silver/
RUN=$(aws glue start-job-run --job-name lottery-transform-prod --query JobRunId --output text)
aws glue get-job-run --job-name lottery-transform-prod --run-id "$RUN" \
  --query 'JobRun.{State:JobRunState,Error:ErrorMessage}' --output table
```

**Verified 2026-07-13 against prod:**

- Lambda → `StatusCode 200`, no `FunctionError`, payload
  `{"status": "ok", "file": "/tmp/results_raw_lottery_url_id_286_...no._3129.txt"}`
- Glue → `SUCCEEDED` (13s, `ErrorMessage: None`)

Failure modes:

- Lambda `Unable to import module 'loteria/extractor/lambda_handler'` → the deployed zip is
  the old one. Re-run `make build` and re-apply.
- Glue `ImportError: can't find '__main__' module in ...zip` → the uploaded zip has no
  root-level `__main__.py`. Re-run `make build` and re-upload; see the Glue section above.

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
