# PR-010 — Migrate the `etl-lambda` module (cross-state move + env-var change)

**Goal:** Move the extractor Lambda and its S3 deployment artifact from the **legacy**
stack (`terraform-lottery/Prod`, key `legacy/terraform.tfstate`) into
`terraform/modules/etl-lambda/` in the **main** stack (key `main/terraform.tfstate`)
**without recreating the function**, AND apply one deliberate change: the function's
env vars switch from bucket ARNs to bucket **names**, plus a new `LOTERIA_SECRET_NAME`.

> **Who runs this:** the repo owner, with prod credentials. Same cross-state pattern as
> PR-007/008/009 (`state rm` + `import`). Like PR-009, the first main `plan` after import
> is **not** a pure no-op — it shows one in-place update to the function (the env vars),
> which you apply. Nothing is destroyed or recreated.

## What moves (2 imported)

- `aws_s3_object.lambda_package` → `module.etl_lambda.aws_s3_object.lambda_package`
- `aws_lambda_function.extractor_lambda` → `module.etl_lambda.aws_lambda_function.extractor_lambda`

## The deliberate env-var change (intended in-place diff)

| Variable | Before (legacy) | After (module) |
|---|---|---|
| `PARTITIONED_BUCKET` | `arn:aws:s3:::lottery-partitioned-storage-prod` | `lottery-partitioned-storage-prod` |
| `SIMPLE_BUCKET` | `arn:aws:s3:::lottery-data-simple-prod` | `lottery-data-simple-prod` |
| `REGION` | `us-east-1` | `us-east-1` (unchanged) |
| `LOTERIA_SECRET_NAME` | — | `lottery_secret_prod_2` (new) |

**Why it's safe:** the extractor code does not read these env vars at all today — it
pulls buckets + token from Secrets Manager (`lambda/extractor/aws_secrets.py`, which
hard-codes the secret name), and its `.split(":::")[-1]` parsing is a no-op on plain
names anyway. PR-017 switches the code to consume `LOTERIA_SECRET_NAME`.

---

## Prerequisites

```bash
export AWS_PROFILE=angel-adming
export AWS_REGION=us-east-1
```

**Pull the deployed zip into `terraform/`** so the config's `filemd5`/`filebase64sha256`
match what is deployed (otherwise the plan will also want to re-upload the artifact):

```bash
cd terraform
aws s3 cp s3://lambda-code-zip-prod/lambda_package.zip lambda_package.zip
```

(`lambda_package.zip` is gitignored via `*.zip`. The root var `lambda_zip_path` defaults
to this path.)

> ⚠️ **Do NOT `terraform apply` the legacy stack until Step 4 verifies a clean plan.**

## Step 1 — Import the 2 resources into the MAIN stack

```bash
cd terraform

# S3 object (import id = bucket/key)
terraform import module.etl_lambda.aws_s3_object.lambda_package lambda-code-zip-prod/lambda_package.zip

# Lambda function (import id = function name)
terraform import module.etl_lambda.aws_lambda_function.extractor_lambda lottery-extractor-prod
```

If any import says "Resource already managed," skip it.

## Step 2 — Remove the 2 from the LEGACY stack

```bash
cd ../terraform-lottery/Prod

terraform state rm \
  aws_s3_object.lambda_package \
  aws_lambda_function.extractor_lambda
```

## Step 3 — Verify the MAIN plan (one in-place update)

```bash
cd ../../terraform
terraform plan
```

**Predicted:** `0 to add, 1 to change, 0 to destroy` — an in-place update to
`module.etl_lambda.aws_lambda_function.extractor_lambda` changing only `environment`
(the table above). Then `terraform apply` and re-plan to `No changes.`

- ⚠️ If the plan also wants to update the `aws_s3_object` (etag) or the function's
  `source_code_hash`, your local `lambda_package.zip` differs from the deployed one —
  redo the `aws s3 cp` in Prerequisites before applying.
- ❌ Any **create** = a missed import (re-run it). Any **destroy/replace** = STOP.

## Step 4 — Verify the LEGACY plan is a no-op

```bash
cd ../terraform-lottery/Prod && terraform plan
```

**Expected:** `No changes.` (the old `lambda_package.zip` etag diff noted in PR-004/007/008
disappears with this PR — the object is no longer in the legacy state).

- ❌ Any **destroy** of the function/object = the `state rm` missed an address. Do not apply.

## Step 5 — Smoke-test

Invoke the function once (or run the Step Function) and confirm it still succeeds — this
proves the env-var change didn't affect it (it shouldn't; the code ignores those vars).

```bash
aws lambda invoke --function-name lottery-extractor-prod \
  --payload '{}' /tmp/extractor_out.json && cat /tmp/extractor_out.json
```

---

## Rollback

Nothing structural changed in AWS. Re-import the 2 resources into legacy at their old
addresses, `state rm module.etl_lambda.*` from main, `git revert`. The env vars revert by
re-applying the old config.

## What this PR touches

- **Adds:** `terraform/modules/etl-lambda/{main,variables,outputs}.tf` + README; wires
  `module.etl_lambda` into the root (role from `module.iam`, buckets from
  `module.storage`); adds root var `lambda_zip_path`; the iam module's
  `extractor_lambda_name` input now comes from the module output (same value → no
  policy diff).
- **Edits (legacy, code only):** `lambdas.tf` → pointer.
- **State ops (owner):** import 2 into main; `state rm` 2 from legacy.
- **Live change:** one in-place Lambda env update (ARNs → names + `LOTERIA_SECRET_NAME`).
