# PR-011 — Migrate the `etl-glue` module (cross-state move, no-op plan)

**Goal:** Move the Glue transform job from the **legacy** stack
(`terraform-lottery/Prod`, key `legacy/terraform.tfstate`) into
`terraform/modules/etl-glue/` in the **main** stack (key `main/terraform.tfstate`)
**without recreating the job**, and drop the hard-coded script location.

> **Who runs this:** the repo owner, with prod credentials. Same cross-state pattern as
> PR-007..010 (`state rm` + `import`). Unlike PR-009/010 there is **no intended diff** —
> the parameterized `script_location` resolves to the exact same string in prod, so the
> plan after import must be a pure no-op.

## What moves (1 imported)

- `aws_glue_job.lottery_transform` → `module.etl_glue.aws_glue_job.lottery_transform`

## Prerequisites

```bash
export AWS_PROFILE=angel-adming
export AWS_REGION=us-east-1
```

Merge order: PR-010 (#11) must already be merged + its state ops done.

> ⚠️ **Do NOT `terraform apply` the legacy stack until Step 3 verifies a clean plan.**

## Step 1 — Import into the MAIN stack

```bash
cd terraform

# Glue job (import id = job name)
terraform import module.etl_glue.aws_glue_job.lottery_transform lottery-transform-prod
```

## Step 2 — Remove from the LEGACY stack

```bash
cd ../terraform-lottery/Prod

terraform state rm aws_glue_job.lottery_transform
```

## Step 3 — Verify BOTH plans are no-ops

```bash
cd ../../terraform && terraform plan
cd ../terraform-lottery/Prod && terraform plan
```

**Expected:** `No changes.` on both.

- ⚠️ If the main plan shows a `script_location` change, the module's
  `code_bucket`/`script_key` don't reproduce `s3://lambda-code-zip-prod/lottery_transformer.zip`
  — STOP and check the wiring, do not apply.
- ❌ Any **create** = a missed import. Any **destroy/replace** = STOP.

## Rollback

Re-import the job into legacy at `aws_glue_job.lottery_transform`, `state rm
module.etl_glue.*` from main, `git revert`.

## What this PR touches

- **Adds:** `terraform/modules/etl-glue/{main,variables,outputs}.tf` + README; wires
  `module.etl_glue` into the root (role from `module.iam`, code bucket from
  `module.storage`); the iam module's `glue_job_name` input now comes from the module
  output (same value → no policy diff).
- **Edits (legacy, code only):** `glue_job.tf` → pointer.
- **State ops (owner):** import 1 into main; `state rm` 1 from legacy.
- **Live change:** none.
