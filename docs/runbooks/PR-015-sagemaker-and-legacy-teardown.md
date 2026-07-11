# PR-015 — SageMaker as an opt-in module + delete `terraform-lottery/`

**Goal:** Move the last legacy resource (the SageMaker Studio domain) into an **opt-in**
module (`count = var.enable_sagemaker ? 1 : 0`, default **false**), then delete the
`terraform-lottery/` folder — leaving `terraform/` as the single Terraform root.

> **Who runs this:** the repo owner. ⚠️ **Ordering matters more than usual**: this PR
> DELETES the legacy `.tf` files, so the final legacy state op must happen **BEFORE you
> pull the merged PR** (while the legacy folder still exists on disk).

## Phase A — BEFORE merging/pulling this PR (legacy folder still intact)

On `master` with PR-014 merged (and PR-010..014 state ops done):

```bash
export AWS_PROFILE=angel-adming AWS_REGION=us-east-1
cd terraform-lottery/Prod

terraform state list
```

**Expected: exactly one resource** — `aws_sagemaker_domain.lottery_domain`.
❌ If anything else is listed, a previous PR's state op was missed — STOP and finish it
first (see that PR's runbook).

```bash
terraform state rm aws_sagemaker_domain.lottery_domain
terraform state list   # must print nothing
```

The domain still exists in AWS — it is just unmanaged for the moment (Phase C re-adopts
it if you want it managed). An empty legacy state means the folder is safe to delete.

## Phase B — Merge + pull, then clean local leftovers

```bash
git checkout master && git pull
# gitignored local files survive the git deletion; remove them by hand:
rm -rf terraform-lottery
```

(That removes the leftover `terraform.tfvars`, `lambda_package.zip`, and `.terraform/`.
Every value from that tfvars is preserved in the runbooks / module defaults.)

Optional: the old state object (empty now) can stay in S3 as history, or be removed:

```bash
aws s3 rm s3://loteria-tf-state-913524903233/legacy/terraform.tfstate   # optional
```

(The bucket is versioned, so even this is recoverable.)

## Phase C — Choose the SageMaker path

**Default (recommended for cost): leave it OFF in Terraform.** `enable_sagemaker` is
false ⇒ `terraform plan` in `terraform/` ignores the domain entirely. The deployed
domain keeps existing in AWS, unmanaged. You can even delete it from the console when
you're not using Studio — `make sagemaker` recreates it on demand (note: a fresh domain
has a new ID and no user profile; see the module README).

**Or: manage the deployed domain.** Set `enable_sagemaker = true` in your gitignored
`terraform/terraform.tfvars`, then import (the index `[0]` matters — the module is
`count`-gated):

```bash
cd terraform
DOMAIN_ID=$(aws sagemaker list-domains --query 'Domains[0].DomainId' --output text)
terraform import "module.sagemaker[0].aws_sagemaker_domain.lottery_domain" "$DOMAIN_ID"
terraform plan   # expect: No changes
```

The `lottery-analyst` **user profile stays unmanaged either way** —
`aws_sagemaker_user_profile` import is broken on aws provider v5.x (`arn: invalid
prefix` read-back bug, known since PR-004). A commented resource in the module
documents it.

## Verify the end state

```bash
cd terraform && terraform plan     # No changes (with your tfvars)
git grep -l "terraform-lottery" -- '*.tf'   # nothing
```

`terraform/` is now the single root. 🎉

## Rollback

`git revert` restores the legacy folder's files; the legacy state (if you kept the S3
object / bucket versioning) still matches an empty or single-resource stack, so
re-importing the domain there is one command.

## What this PR touches

- **Adds:** `terraform/modules/sagemaker/` (domain only; profile documented as
  unmanaged), root `module "sagemaker"` with `count = var.enable_sagemaker ? 1 : 0`.
- **Fills in:** the `make sagemaker` target
  (`terraform apply -var=enable_sagemaker=true -target=module.sagemaker`).
- **Deletes:** the entire `terraform-lottery/` folder (every resource was migrated via
  cross-state `state rm` + `import` in PR-007..PR-012 + Phase A above; PR-013/014 were
  new resources).
- **Edits:** README points at `terraform/` (full rewrite comes in PR-036).
- **State ops (owner):** Phase A `state rm` (1); Phase C optional import (1).
- **Live change:** none.
