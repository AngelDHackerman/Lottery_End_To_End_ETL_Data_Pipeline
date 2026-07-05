# PR-005 — Import the prod data buckets into Terraform (with `prevent_destroy`)

**Goal:** Bring the two real, irreplaceable data buckets under Terraform management
**without changing any live infrastructure**, and lock them down with
`prevent_destroy = true`. Proven by `terraform plan` == no changes.

| Bucket resource | Real bucket name |
|---|---|
| `aws_s3_bucket.lottery_partitioned` | `lottery-partitioned-storage-prod` |
| `aws_s3_bucket.lottery_simple` | `lottery-data-simple-prod` |

> **Why these weren't done in PR-004:** the PR-004 state reconstruction imported the
> buckets that were *live in the `.tf`* (`lambda_code_zip`, `athena_results`). These two
> data buckets were commented out, so they stayed unmanaged. PR-005 uncomments them,
> adds guardrails, and imports them.

> **Who runs this:** the repo owner, in their AWS account, with prod credentials.
> The agent wrote the `s3.tf` changes and this runbook. Nothing here runs in CI.

---

## Prerequisites

- PR-004 merged: the legacy stack is remote-backed at
  `s3://loteria-tf-state-913524903233/legacy/terraform.tfstate` and
  `terraform plan` is currently a no-op.
- Both buckets already have (from PR-002): **Versioning = Enabled** and the
  **deny-delete bucket policy**. That's why importing versioning below is a no-op, and
  why we do **not** model the bucket policy in Terraform.
- Prod credentials exported:
  ```bash
  export AWS_PROFILE=angel-adming     # or your prod profile
  export AWS_REGION=us-east-1
  ```
- Your `terraform.tfvars` for `terraform-lottery/Prod` is present (gitignored).

## Step 1 — Init (if this is a fresh checkout)

```bash
cd terraform-lottery/Prod
terraform init \
  -backend-config="bucket=loteria-tf-state-913524903233" \
  -backend-config="region=us-east-1"
```

If the backend is already initialized in your working copy, skip this.

## Step 2 — Import the buckets and their sub-resources

For `aws_s3_bucket*` resources the **import ID is just the bucket name** (no ARN, no
prefix). Run all six from `terraform-lottery/Prod/`:

```bash
# --- lottery-partitioned-storage-prod ---
terraform import aws_s3_bucket.lottery_partitioned                              lottery-partitioned-storage-prod
terraform import aws_s3_bucket_versioning.lottery_partitioned                   lottery-partitioned-storage-prod
terraform import aws_s3_bucket_server_side_encryption_configuration.lottery_partitioned lottery-partitioned-storage-prod
terraform import aws_s3_bucket_public_access_block.lottery_partitioned          lottery-partitioned-storage-prod

# --- lottery-data-simple-prod ---
terraform import aws_s3_bucket.lottery_simple                                   lottery-data-simple-prod
terraform import aws_s3_bucket_versioning.lottery_simple                        lottery-data-simple-prod
terraform import aws_s3_bucket_server_side_encryption_configuration.lottery_simple lottery-data-simple-prod
terraform import aws_s3_bucket_public_access_block.lottery_simple               lottery-data-simple-prod
```

Each import is idempotent in effect — if a resource is already in state, Terraform
errors with "Resource already managed"; that's fine, move on to the next.

## Step 3 — Verify the plan is a no-op (the acceptance gate)

```bash
terraform plan
```

**MUST report `No changes. Your infrastructure matches the configuration.`**

- ✅ Empty plan → success. Both buckets are now managed, with `prevent_destroy`.
- ⚠️ **In-place-only diffs are acceptable** — note them in the PR and apply if trivial.
  The likely candidates:
  - **Tags.** The `.tf` sets `Name / Environment / Owner / Project`. If the live buckets
    were created with different (or no) tags, `plan` shows an in-place tag update. Safe
    to apply — tags don't affect data.
  - **SSE / PAB / versioning** should import as no-ops because PR-002 already set them.
- ❌ Any **create / destroy / replace** of a bucket → **STOP**. Do not apply. A
  create means an import was missed; a destroy/replace means a name mismatch. Because
  `prevent_destroy = true` is set, Terraform will in fact *hard-error* rather than plan a
  destroy of these buckets — that guardrail is intentional. Re-check the import IDs.

## Step 4 — Confirm `prevent_destroy` actually protects the buckets (optional sanity)

You can prove the guardrail without deleting anything: temporarily point at a throwaway
plan that would delete the bucket (e.g. comment the resource) and confirm Terraform
refuses with:

```
Error: Instance cannot be destroyed ... has lifecycle.prevent_destroy set
```

Then revert. **Do not `terraform destroy`.** (There is no need to actually run this;
it's just how you'd demonstrate the lock.)

---

## Rollback

Import only writes state; no AWS resource is touched.

1. Remove the buckets from state (they stay in AWS, fully intact):
   ```bash
   for r in aws_s3_bucket aws_s3_bucket_versioning \
            aws_s3_bucket_server_side_encryption_configuration \
            aws_s3_bucket_public_access_block; do
     terraform state rm "$r.lottery_partitioned" "$r.lottery_simple" 2>/dev/null || true
   done
   ```
2. Re-comment the resource blocks in `s3.tf` if you want the config back to pre-PR-005.
3. Nothing on the infra side to revert.

---

## What this PR touches

- **Adds (state only):** the two data buckets + their versioning/SSE/PAB sub-resources
  to `legacy/terraform.tfstate` via `terraform import`.
- **Edits:** `terraform-lottery/Prod/s3.tf` — uncomments the two buckets, renames them
  (`lottery_raw_data` → `lottery_partitioned`, `lottery_data_simple` → `lottery_simple`),
  sets `prevent_destroy = true`, and adds versioning / SSE (AES256) / public-access-block.
- **Does NOT:** add `force_destroy`, remove the PR-002 deny-delete bucket policy, or
  change any live AWS resource.
