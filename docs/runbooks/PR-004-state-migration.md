# PR-004 — Reconstruct legacy Terraform state into the remote backend

> **Plan change.** PR-004 was originally "migrate the existing local state to S3 and
> verify an empty plan." During execution we discovered the legacy state for
> `terraform-lottery/Prod/` **no longer exists anywhere** — it was gitignored
> (`*.tfstate`), never committed, and no local copy survives. The 67 resources still
> live in AWS. So this PR **rebuilds** the state via `terraform import` instead of
> moving it. Same end goal: `terraform-lottery/Prod` managed from the remote backend
> with a no-op plan.

**Goal:** A fresh remote-backed state at
`s3://loteria-tf-state-913524903233/legacy/terraform.tfstate` that matches the
deployed AWS resources, proven by `terraform plan` == no changes.

> **Who runs this:** the repo owner, in their AWS account, with prod credentials.
> The agent wrote `backend.tf`, `scripts/reconstruct_legacy_state.sh`, and this
> runbook. Nothing here runs in CI.

---

## Prerequisites

- PR-003 applied: state bucket `loteria-tf-state-913524903233` and lock table
  `loteria-tf-locks` exist (confirm with `terraform output` in `terraform/bootstrap/`).
- Prod credentials exported:
  ```bash
  export AWS_PROFILE=<your-prod-profile>
  export AWS_REGION=us-east-1
  export ENV=prod            # resource-name suffix used across the config
  ```
- Your `terraform.tfvars` for `terraform-lottery/Prod` is present (it's gitignored;
  the import step needs the provider + variables to resolve). Note your
  `enable_internet` value — it decides whether the NAT-path resources exist.

## Step 1 — Init the fresh remote backend (NO `-migrate-state`)

There is no local state to migrate, so we just point at S3 and let Terraform create
an empty state there. `backend.tf` bakes in `key=legacy/terraform.tfstate` and the
lock table; pass only `bucket` + `region` (do **not** reuse `terraform/backend.hcl` —
it pins the *main* stack's key):

```bash
cd terraform-lottery/Prod
terraform init \
  -backend-config="bucket=loteria-tf-state-913524903233" \
  -backend-config="region=us-east-1"
```

## Step 2 — Import all resources

Run the import script (idempotent — safe to re-run; already-imported resources are
skipped):

```bash
ENABLE_INTERNET=false \
  bash ../../scripts/reconstruct_legacy_state.sh
```

Set `ENABLE_INTERNET=true` **only** if you deployed with `enable_internet = true`
(then the IGW/EIP/NAT/route resources exist and get imported too).

If any single import fails (e.g. a name mismatch because your real `ENV` differs, or
a resource was created manually with a different name), the script stops. Fix that one
`terraform import` by hand, then re-run the script — it resumes from where it left off.

## Step 3 — Handle the 5 non-importable resources

Terraform **cannot** import these (provider limitations), so a plan will want to
CREATE them. The import script auto-skips Lake Formation + the SageMaker user profile;
you must comment all five out of the `.tf` so the plan is a true no-op:

| Resource | Why it can't be imported | What to do |
|---|---|---|
| `null_resource.run_glue_crawlers` | No cloud identity; apply-time trigger only | Comment it out (`# TODO PR-012`) |
| `null_resource.run_silver_glue_crawlers` | Same | Comment it out (`# TODO PR-012`) |
| `aws_iam_policy_attachment.glue_service_policy` | `aws_iam_policy_attachment` has no import support, and it's an **exclusive** attachment on an AWS-managed policy (dangerous) | Comment it out (`# TODO PR-009`); PR-009 replaces it with `aws_iam_role_policy_attachment` |
| `aws_lakeformation_resource.athena_results_location` | `aws_lakeformation_resource` has no import support; set up **manually** in AWS | Comment it out (`# TODO PR-013`); stays manually-managed until PR-013 codifies Lake Formation |
| `aws_sagemaker_user_profile.lottery_user` | Import fails with `arn: invalid prefix` on aws provider v5.x — a **provider read-back bug**, not a config issue | Comment it out (`# TODO PR-015`); SageMaker becomes an opt-in module in PR-015. The domain itself imported fine |

Comment those five blocks out. These are the only deliberate `.tf` edits in this PR;
everything else is state-only. With them removed from config, the plan becomes a true
no-op.

> If you'd rather not edit resources yet, you can instead accept a plan that shows
> exactly those 5 creates — but then Step 4's gate is "no changes **except** those 5,"
> which is harder to eyeball. Commenting out is cleaner.

## Step 4 — Verify the plan is a no-op (the acceptance gate)

```bash
terraform plan
```

**MUST report `No changes. Your infrastructure matches the configuration.`**

- ✅ Empty plan → success. The state is reconstructed and remote.
- ⚠️ Only in-place metadata/tag diffs → acceptable; note them in the PR and apply if
  trivial. Expect a possible diff on:
  - `aws_s3_object.lambda_package` (etag vs the local `lambdas_path_local` zip) — if
    the local zip differs from what's in S3, TF wants to re-upload. Point
    `lambdas_path_local` at the deployed artifact, or accept the re-upload.
- ❌ Any create/**destroy**/replace of real infra → **STOP**. Do not apply. The config
  drifted from reality (or a name/ID is wrong). Open an issue with the plan output.

## Step 5 — Confirm state landed in S3

```bash
aws s3 ls "s3://loteria-tf-state-913524903233/legacy/"
# expect: legacy/terraform.tfstate
terraform state list | wc -l    # 62 (67 blocks − 5 non-importable, with enable_internet=false so the 5 NAT resources are count=0)
```

---

## Rollback

State reconstruction only writes a new state object; it does not change infra. To bail:

1. Delete the reconstructed state object:
   `aws s3 rm "s3://loteria-tf-state-913524903233/legacy/terraform.tfstate"`
   (versioning is on, so it's recoverable anyway).
2. Remove/rename `backend.tf` and `terraform init` back to local if desired.
3. No AWS resources were touched, so nothing to revert on the infra side.

---

## What this PR touches

- **Adds:** `terraform-lottery/Prod/backend.tf`, `scripts/reconstruct_legacy_state.sh`,
  this runbook.
- **Edits (Step 3, owner):** comments out 2 `null_resource`s, 1
  `aws_iam_policy_attachment`, 1 `aws_lakeformation_resource`, and 1
  `aws_sagemaker_user_profile` — all slated for deletion/replacement in PR-009/012/013/015.
- **Does NOT** change any live AWS resource. Reconstruction is state-only (the one-time
  `terraform apply` only writes Terraform-side attributes — `force_destroy`, the Lambda
  `source_code_hash`/`s3_key` pointing at identical code — no infra behavior changes).

PR-005 (import the two prod data buckets with `prevent_destroy`) comes next — don't
start it until this plan verifies clean.

---

## Appendix — Reconstructing state / tfvars from a live account

If you ever lose the state **and** the tfvars again (or inherit an account with no
Terraform config history), here's the manual recovery playbook this PR followed. The
core idea: **the config already tells you what to look for; AWS holds the values.**

### A. Recover the variable values (`terraform.tfvars`)

1. **List what's required.** In `variables.tf`, every `variable` with **no `default`**
   must be supplied. Those are your targets:
   ```bash
   # rough list of required (no-default) variables
   grep -A3 '^variable' variables.tf | grep -B2 -L 'default'   # or just read the file
   ```
2. **Find where each is used** — this tells you which real AWS resource holds the value:
   ```bash
   grep -rn "var.aws_availability_zone_a" *.tf   # -> aws_subnet.private_a.availability_zone
   ```
3. **Read the value off AWS** (console or CLI). Examples used here:
   ```bash
   aws sts get-caller-identity --query Account --output text          # aws_account_id
   aws ec2 describe-subnets --filters Name=tag:Name,Values=priv-subnet-a-prod \
     --query 'Subnets[0].AvailabilityZone' --output text              # AZ (must match exactly!)
   aws s3 ls | grep lottery                                           # bucket names
   aws iam list-roles --query "Roles[?contains(RoleName,'lottery')].Arn"
   ```
4. **Variables with 0 usages** (`grep` returns nothing) are dead — any valid placeholder
   works; they only exist to stop Terraform's interactive prompts.
5. **Danger class:** values that feed *immutable* attributes (subnet AZ, CIDRs) or that
   are baked into a rendered document (the Step Function `definition` reading
   `var.glue_crawler_*`). Get these wrong and `plan` shows a **replace** or a bad
   in-place edit. Confirm them against reality before trusting `plan`.

### B. Recover the state file

- **If state exists anywhere** (S3 with versioning, a teammate's machine, a backup):
  restore it — you're instantly whole, and you can even read every resolved attribute
  back out (`terraform show`, `terraform state show <addr>`) without the tfvars.
- **If state is truly gone** (this PR's case): rebuild it with `terraform import`, one
  resource per real object, then `terraform plan` until it's a no-op. See
  `scripts/reconstruct_legacy_state.sh` for the full import list and the ID formats per
  resource type (bucket = name, IAM role = name, IAM policy = ARN, role attachment =
  `role/policy-arn`, event rule = `bus/rule`, glue db = `account:db`, SFN = ARN, etc.).
- **Newer alternative:** `import {}` blocks + `terraform plan -generate-config-out=…`
  (TF 1.5+) will generate *both* the state and draft HCL from live resources — handy
  when you've also lost the `.tf`, not just the state.

### C. The lesson

This whole exercise is what the remote-state backend (PR-003) exists to prevent. With
state in the versioned S3 bucket + DynamoDB lock, losing it becomes nearly impossible,
and even a lost `tfvars` is recoverable by reading attributes straight out of state.
