# PR-007 — Migrate the `storage` module (cross-state move of the S3 buckets)

**Goal:** Move the four S3 buckets (and their sub-resources) from the **legacy** stack
(`terraform-lottery/Prod`, state key `legacy/terraform.tfstate`) into
`terraform/modules/storage/` in the **main** stack (state key `main/terraform.tfstate`),
**without recreating anything**. Proven by a no-op `terraform plan` on *both* stacks.

> **Who runs this:** the repo owner, with prod credentials. The agent wrote the module,
> the root wiring, the legacy edits, and this runbook. No AWS resource is destroyed or
> created — this is pure state bookkeeping.

## Why `state rm` + `import` instead of `terraform state mv`

The roadmap says "use `terraform state mv`." That verb assumes **one** state file. Here the
source and destination live in **two separate remote states** (legacy vs main), so a plain
`state mv` doesn't apply — you'd need the fragile `terraform state pull | mv -state/-state-out | push`
dance, with lineage/serial pitfalls. Instead we use the equivalent, safer pair:

- `terraform state rm` in the **legacy** stack → forget the resource (leaves it in AWS).
- `terraform import` in the **main** stack → adopt the same real resource into `module.storage`.

We already proved these exact imports produce a clean plan in PR-005, and all sub-resources
now exist in AWS (applied in PR-005), so every import is a no-op. `state rm` does **not**
evaluate `lifecycle`, so `prevent_destroy` does not block it (and nothing is destroyed).

---

## Prerequisites

```bash
export AWS_PROFILE=angel-adming     # prod profile
export AWS_REGION=us-east-1
```
- Both stacks already init'd against the S3 backend (main was init'd in PR-006).
- The code changes in this PR are already on your branch: the buckets now live in
  `terraform/modules/storage/`, the root calls `module.storage`, and the legacy stack no
  longer declares them (s3.tf is a pointer; athena/iam/lambdas reference the bucket names
  as literal strings).

> ⚠️ **Do NOT run `terraform apply` on the legacy stack until Step 3 verifies a clean
> plan.** Between the code change and the `state rm`, the legacy *config* no longer
> declares these buckets while the legacy *state* still tracks them — an apply there would
> attempt to destroy them (the two data buckets' `prevent_destroy` would hard-error and
> halt, but don't rely on that; just don't apply).

---

## Step 1 — Import the 13 resources into the MAIN stack

Do this **first** (additive; leaves the legacy state untouched, so the buckets are always
tracked by at least one state). Import IDs for `aws_s3_bucket*` = the bucket name.

```bash
cd terraform

# --- lottery-partitioned-storage-prod ---
terraform import module.storage.aws_s3_bucket.lottery_partitioned                              lottery-partitioned-storage-prod
terraform import module.storage.aws_s3_bucket_versioning.lottery_partitioned                   lottery-partitioned-storage-prod
terraform import module.storage.aws_s3_bucket_server_side_encryption_configuration.lottery_partitioned lottery-partitioned-storage-prod
terraform import module.storage.aws_s3_bucket_public_access_block.lottery_partitioned          lottery-partitioned-storage-prod

# --- lottery-data-simple-prod ---
terraform import module.storage.aws_s3_bucket.lottery_simple                                   lottery-data-simple-prod
terraform import module.storage.aws_s3_bucket_versioning.lottery_simple                        lottery-data-simple-prod
terraform import module.storage.aws_s3_bucket_server_side_encryption_configuration.lottery_simple lottery-data-simple-prod
terraform import module.storage.aws_s3_bucket_public_access_block.lottery_simple               lottery-data-simple-prod

# --- lambda-code-zip-prod ---
terraform import module.storage.aws_s3_bucket.lambda_code_zip                                  lambda-code-zip-prod

# --- lottery-athena-results-prod ---
terraform import module.storage.aws_s3_bucket.athena_results                                   lottery-athena-results-prod
terraform import module.storage.aws_s3_bucket_public_access_block.athena_results               lottery-athena-results-prod
terraform import module.storage.aws_s3_bucket_server_side_encryption_configuration.athena_results lottery-athena-results-prod
terraform import module.storage.aws_s3_bucket_lifecycle_configuration.athena_results           lottery-athena-results-prod
```

If any import says "Resource already managed," it's already done — skip it. The main stack
needs no tfvars (`environment` defaults to `prod`).

Sanity-check the main plan now:
```bash
terraform plan   # expect: No changes. (all 13 imported, config matches)
```

## Step 2 — Remove the same 13 from the LEGACY stack

`state rm` forgets them in the legacy state (they stay in AWS, now owned by the main
state). One command, all 13 addresses:

```bash
cd ../terraform-lottery/Prod

terraform state rm \
  aws_s3_bucket.lottery_partitioned \
  aws_s3_bucket_versioning.lottery_partitioned \
  aws_s3_bucket_server_side_encryption_configuration.lottery_partitioned \
  aws_s3_bucket_public_access_block.lottery_partitioned \
  aws_s3_bucket.lottery_simple \
  aws_s3_bucket_versioning.lottery_simple \
  aws_s3_bucket_server_side_encryption_configuration.lottery_simple \
  aws_s3_bucket_public_access_block.lottery_simple \
  aws_s3_bucket.lambda_code_zip \
  aws_s3_bucket.athena_results \
  aws_s3_bucket_public_access_block.athena_results \
  aws_s3_bucket_server_side_encryption_configuration.athena_results \
  aws_s3_bucket_lifecycle_configuration.athena_results
```

## Step 3 — Verify BOTH plans are no-ops (the acceptance gate)

```bash
# main stack
cd ../../terraform && terraform plan

# legacy stack
cd ../terraform-lottery/Prod && terraform plan
```

**Both MUST report `No changes. Your infrastructure matches the configuration.`**

- ✅ Both empty → success. The buckets are now owned by `module.storage`; the legacy stack
  no longer references or tracks them.
- ⚠️ On the **legacy** plan, a possible in-place diff on `aws_s3_object.lambda_package`
  (etag vs the local `lambdas_path_local` zip) can appear — same pre-existing note as
  PR-004, unrelated to this move. Safe to ignore/apply.
- ❌ Any **create / destroy / replace of a bucket** on either side → **STOP**. On main, a
  "create" means an import was missed (re-run it). On legacy, a "destroy" means the
  `state rm` didn't cover an address. Do not apply; reconcile first.

---

## Rollback

Nothing in AWS changed, so rollback is just moving state bookkeeping back:

1. Re-import the 13 into the legacy stack (same IDs, non-`module.storage` addresses), and
   `terraform state rm module.storage.<...>` them out of the main stack.
2. Or `git revert` this PR's code changes and re-import into legacy.

Because `versioning` is on and the PR-002 deny-delete policy is still attached, the bucket
data is safe throughout.

---

## What this PR touches

- **Adds:** `terraform/modules/storage/{main,variables,outputs}.tf` (the 4 buckets + subs)
  and wires `module.storage` into `terraform/main.tf`.
- **Edits (legacy, code only — no live change):** `s3.tf` → pointer comment;
  `athena.tf`, `iam.tf`, `lambdas.tf` → the three references to the moved buckets replaced
  with literal names/ARNs that resolve to identical values (so the legacy plan stays no-op).
- **State ops (owner):** `import` 13 into main, `state rm` 13 from legacy.
- **Does NOT:** create, destroy, or modify any live AWS resource.
