# PR-005 — Import the prod data buckets into Terraform (with `prevent_destroy`)

**Goal:** Bring the two real, irreplaceable data buckets under Terraform management by
**importing the buckets** (so no bucket is ever recreated), lock them with
`prevent_destroy = true`, and add versioning / SSE / public-access-block config. The
buckets import with no diff; the only live change is turning on the two public-access
blocks (safe hardening on private data buckets). No bucket contents are touched.

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

## Step 2 — Import the two buckets

The **buckets themselves** must be imported so `prevent_destroy` attaches to the real
objects (never let Terraform "create" them). For `aws_s3_bucket*` resources the
**import ID is just the bucket name** (no ARN, no prefix). Run from
`terraform-lottery/Prod/`:

```bash
terraform import aws_s3_bucket.lottery_partitioned lottery-partitioned-storage-prod
terraform import aws_s3_bucket.lottery_simple      lottery-data-simple-prod
```

If a resource is already in state, Terraform errors with "Resource already managed" —
that's fine, move on.

### The 6 sub-resources: apply, don't import

The versioning / SSE / public-access-block blocks are **config resources**, not the
data. Importing them is optional and, for the PABs, impossible:

| Sub-resource | State on the live bucket | Result of applying (creating) it |
|---|---|---|
| `aws_s3_bucket_versioning` (×2) | Enabled (turned on in PR-002) | **No-op** — writes `Enabled` onto already-`Enabled` |
| `aws_s3_bucket_server_side_encryption_configuration` (×2) | S3 default SSE-S3 (AES256) is already effectively on | **No-op** — codifies what's already true |
| `aws_s3_bucket_public_access_block` (×2) | **Not set** (PR-002 added a deny-delete *policy*, not a PAB) | **Real, safe hardening** — turns on public-access blocking |

Because the two PABs genuinely don't exist yet, a **pure "No changes" plan is not
achievable** — they must be created. So don't chase importing all 8 things; just let
`apply` create these 6 (see Step 3). You *may* import the 4 versioning/SSE resources
(ID = bucket name) to shrink the plan to the 2 PAB creates, but it buys nothing since
you're applying either way.

## Step 3 — Verify the plan, then apply (the acceptance gate)

```bash
terraform plan
```

**Expected: `Plan: 6 to add, 0 to change, 0 to destroy.`** — the six sub-resource
blocks above, and *nothing else*. That is the success condition for this PR.

- ✅ **6 additive, 0 change, 0 destroy** → correct. `prevent_destroy` is on the buckets,
  no data is touched. Run `terraform apply` to codify versioning/SSE (no-ops) and turn on
  the two public-access blocks (safe hardening). If you imported the versioning/SSE
  resources first, expect `2 to add` (just the PABs) instead.
- ⚠️ **In-place tag diffs** on the buckets are also acceptable — the `.tf` sets
  `Name / Environment / Owner / Project`; if the live buckets had different (or no) tags,
  `plan` shows an in-place update. Safe to apply — tags don't affect data.
- ❌ Any **create of `aws_s3_bucket.lottery_*`** (not just the sub-resources), or any
  **destroy / replace** → **STOP**. A bucket "create" means its import was missed; a
  destroy/replace means a name mismatch. `prevent_destroy = true` will hard-error rather
  than plan a destroy of these buckets — that guardrail is intentional.
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

Before `apply`, import only writes state — no AWS resource is touched. After `apply`,
the only live change is the two public-access blocks; to undo them, delete the PAB
resources (`terraform destroy -target=aws_s3_bucket_public_access_block.lottery_partitioned -target=...`)
or remove the blocks from `s3.tf` and re-apply. The buckets and their data are never at risk.

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

- **Imports (state only):** the two `aws_s3_bucket` objects into
  `legacy/terraform.tfstate` — no bucket is recreated, no contents touched.
- **Applies (live, additive):** versioning (no-op), SSE AES256 (no-op), and — the one
  genuine change — the two `aws_s3_bucket_public_access_block`s, hardening the private
  data buckets. `Plan: 6 to add, 0 to change, 0 to destroy`.
- **Edits:** `terraform-lottery/Prod/s3.tf` — uncomments the two buckets, renames them
  (`lottery_raw_data` → `lottery_partitioned`, `lottery_data_simple` → `lottery_simple`),
  sets `prevent_destroy = true`, and adds versioning / SSE (AES256) / public-access-block.
- **Does NOT:** add `force_destroy`, remove the PR-002 deny-delete bucket policy, recreate
  or destroy any bucket, or touch any object in either bucket.
