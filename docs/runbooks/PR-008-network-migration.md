# PR-008 — Migrate the `network` module (cross-state move of the VPC stack)

**Goal:** Move the networking resources from the **legacy** stack
(`terraform-lottery/Prod`, state key `legacy/terraform.tfstate`) into
`terraform/modules/network/` in the **main** stack (state key `main/terraform.tfstate`),
**without recreating anything**. Proven by a no-op `terraform plan` on *both* stacks.

> **Who runs this:** the repo owner, with prod credentials. The agent wrote the module,
> the root wiring, the legacy edits, and this runbook. No AWS resource is destroyed or
> created — this is pure state bookkeeping.

## Why `state rm` + `import` instead of `terraform state mv`

Same reason as PR-007: the source (legacy) and destination (main) are **two separate
remote states**, so a plain `terraform state mv` doesn't apply. We use the equivalent,
safer pair:

- `terraform state rm` in the **legacy** stack → forget the resource (leaves it in AWS).
- `terraform import` in the **main** stack → adopt the same real resource into
  `module.network`.

## What moves (11 resources)

`enable_internet` is **false** in prod, so the NAT / IGW / EIP / default-route resources
are `count = 0` — they do **not** exist in AWS and are **not** imported. The module still
carries their code so the egress path can be turned on later. Only these 11 exist and move:

| Address | Real ID |
|---|---|
| `aws_vpc.lottery` | `vpc-0fadac4b71ca76304` |
| `aws_subnet.private_a` | `subnet-09ef51bcc7e17e8e7` |
| `aws_subnet.private_b` | `subnet-0419da5b53dba0caf` |
| `aws_subnet.public` | `subnet-0265debc002fe82db` |
| `aws_route_table.public_rt` | `rtb-0054f3d18c0e386ae` |
| `aws_route_table.private_rt` | `rtb-0bf322b5258c586f4` |
| `aws_route_table_association.public_assoc` | `subnet-0265debc002fe82db/rtb-0054f3d18c0e386ae` |
| `aws_route_table_association.private_a_assoc` | `subnet-09ef51bcc7e17e8e7/rtb-0bf322b5258c586f4` |
| `aws_route_table_association.private_b_assoc` | `subnet-0419da5b53dba0caf/rtb-0bf322b5258c586f4` |
| `aws_vpc_endpoint.s3` | `vpce-0e9af20f880a7cf6e` |
| `aws_security_group.sagemaker_studio` | `sg-0972cb28f1deb67a8` |

> Route-table-association import IDs use the `SUBNET_ID/ROUTE_TABLE_ID` form (not the
> `rtbassoc-…` id).

---

## Prerequisites

```bash
export AWS_PROFILE=angel-adming     # prod profile
export AWS_REGION=us-east-1
```
- Both stacks already init'd against the S3 backend.
- The code changes in this PR are on your branch: the network resources now live in
  `terraform/modules/network/`, the root calls `module.network`, `network.tf` in the
  legacy stack is a pointer comment, and `sagemaker.tf` references the VPC / subnets / SG
  as **literal IDs** (identical values) so the legacy config still validates.

> ⚠️ **Do NOT run `terraform apply` on the legacy stack until Step 3 verifies a clean
> plan.** Between the code change and the `state rm`, the legacy *config* no longer
> declares these resources while the legacy *state* still tracks them — an apply there
> would try to destroy them. Just don't apply.

---

## Step 1 — Import the 11 resources into the MAIN stack

Do this **first** (additive; leaves the legacy state untouched, so every resource is always
tracked by at least one state). The main stack needs no tfvars (`environment` defaults to
`prod`, region `us-east-1`, AZs `us-east-1a/1b`).

```bash
cd terraform

terraform import module.network.aws_vpc.lottery                                vpc-0fadac4b71ca76304
terraform import module.network.aws_subnet.private_a                           subnet-09ef51bcc7e17e8e7
terraform import module.network.aws_subnet.private_b                           subnet-0419da5b53dba0caf
terraform import module.network.aws_subnet.public                              subnet-0265debc002fe82db
terraform import module.network.aws_route_table.public_rt                      rtb-0054f3d18c0e386ae
terraform import module.network.aws_route_table.private_rt                     rtb-0bf322b5258c586f4
terraform import module.network.aws_route_table_association.public_assoc       subnet-0265debc002fe82db/rtb-0054f3d18c0e386ae
terraform import module.network.aws_route_table_association.private_a_assoc    subnet-09ef51bcc7e17e8e7/rtb-0bf322b5258c586f4
terraform import module.network.aws_route_table_association.private_b_assoc    subnet-0419da5b53dba0caf/rtb-0bf322b5258c586f4
terraform import module.network.aws_vpc_endpoint.s3                            vpce-0e9af20f880a7cf6e
terraform import module.network.aws_security_group.sagemaker_studio           sg-0972cb28f1deb67a8
```

If any import says "Resource already managed," it's already done — skip it.

Sanity-check the main plan now:
```bash
terraform plan   # expect: No changes.
```

> Unlike PR-007 (the athena bucket's `force_destroy` flag), nothing here has a
> Terraform-only attribute, so the plan should be clean with **no** apply needed. If you
> see a proposed **replace** of a subnet, the AZ vars don't match the live subnet — STOP
> and reconcile `aws_availability_zone_a/b` (see the `variables.tf` defaults) before
> continuing.

## Step 2 — Remove the same 11 from the LEGACY stack

`state rm` forgets them in the legacy state (they stay in AWS, now owned by the main
state). One command, all 11 addresses:

```bash
cd ../terraform-lottery/Prod

terraform state rm \
  aws_vpc.lottery \
  aws_subnet.private_a \
  aws_subnet.private_b \
  aws_subnet.public \
  aws_route_table.public_rt \
  aws_route_table.private_rt \
  aws_route_table_association.public_assoc \
  aws_route_table_association.private_a_assoc \
  aws_route_table_association.private_b_assoc \
  aws_vpc_endpoint.s3 \
  aws_security_group.sagemaker_studio
```

## Step 3 — Verify BOTH plans are no-ops (the acceptance gate)

```bash
# main stack
cd ../../terraform && terraform plan

# legacy stack
cd ../terraform-lottery/Prod && terraform plan
```

**Both MUST report `No changes. Your infrastructure matches the configuration.`**

- ✅ Both empty → success. The network is now owned by `module.network`; the legacy stack
  no longer references or tracks it, and `aws_sagemaker_domain` still points at the same
  VPC / subnets / SG via literal IDs.
- ⚠️ Acceptable in-place diff (legacy only): a possible diff on
  `aws_s3_object.lambda_package` (etag vs the local `lambdas_path_local` zip) — same
  pre-existing note as PR-004/PR-007, unrelated to this move.
- ❌ Any **create / destroy / replace** of a VPC / subnet / route table / SG / endpoint on
  either side → **STOP**. On main, a "create" means an import was missed (re-run it). On
  legacy, a "destroy" means the `state rm` didn't cover an address. Do not apply; reconcile
  first.

---

## Rollback

Nothing in AWS changes, so rollback is just moving state bookkeeping back:

1. Re-import the 11 into the legacy stack (same IDs, non-`module.network` addresses), and
   `terraform state rm module.network.<...>` them out of the main stack.
2. Or `git revert` this PR's code changes and re-import into legacy.

---

## What this PR touches

- **Adds:** `terraform/modules/network/{main,variables,outputs}.tf` (the VPC stack) and
  wires `module.network` into `terraform/main.tf`; adds `aws_availability_zone_a/b`
  variables (defaults `us-east-1a/1b`) to the root `variables.tf`.
- **Edits (legacy, code only — no live change):** `network.tf` → pointer comment;
  `sagemaker.tf` → the four references to the VPC / subnets / SG replaced with literal IDs
  that resolve to identical values (so the legacy plan stays no-op).
- **State ops (owner):** `import` 11 into main, `state rm` 11 from legacy.
- **Does NOT:** create, destroy, or modify any live AWS resource.
