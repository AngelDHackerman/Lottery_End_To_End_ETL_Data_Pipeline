# PR-013 — Codify Lake Formation (new resources, no state moves)

**Goal:** Turn the manual Lake Formation console setup (challanges_faced.md §5) into
Terraform, so a fresh account deploy needs zero LF console clicks before the silver
crawlers run.

> **Who runs this:** the repo owner, with prod credentials. **Different from
> PR-007..012:** there is nothing to `state rm` or `import` — `aws_lakeformation_resource`
> does not support import, and LF permission grants are additive. This is a plain
> `terraform apply` that creates up to 5 resources.

## What gets created

1. `module.lake_formation.aws_lakeformation_resource.silver` — registers
   `s3://lottery-partitioned-storage-prod/silver` with the
   `AWSServiceRoleForLakeFormationDataAccess` service-linked role.
2. `...aws_lakeformation_permissions.crawler_database` — `CREATE_TABLE, ALTER, DROP,
   DESCRIBE` on `lottery_santalucia_db` → `glue-crawler-role`.
3. `...aws_lakeformation_permissions.crawler_all_tables` — `ALL` (Super) on all tables
   in the db → `glue-crawler-role` (matches the existing manual grant; a narrower grant
   would read back as perpetual drift).
4. `...aws_lakeformation_permissions.crawler_silver_location` — `DATA_LOCATION_ACCESS`
   on the silver path → `glue-crawler-role`.
5. `...aws_lakeformation_permissions.iam_allowed_principals_compat[0]` — the Hybrid
   access mode compat grant (gated by `enable_iam_allowed_principals_compat`, default
   true).

## Step 1 — Check what's already registered

The manual setup registered `processed/`; `silver/` may or may not also be registered:

```bash
export AWS_PROFILE=angel-adming AWS_REGION=us-east-1
aws lakeformation list-resources
```

- If `.../silver` (exactly) is **already registered**: the apply of
  `aws_lakeformation_resource.silver` will fail with `AlreadyExistsException`.
  Deregister the manual entry first, then let Terraform own it:
  ```bash
  aws lakeformation deregister-resource --resource-arn arn:aws:s3:::lottery-partitioned-storage-prod/silver
  ```
  (Deregistering only removes the LF registration — no data is touched. Re-registration
  by the apply is immediate.)
- A registration of a *different* path (e.g. `/processed`) does not conflict — leave it.

## Step 2 — Apply

```bash
cd terraform
terraform plan    # expect: 5 to add (4 if the compat grant is disabled), 0 change, 0 destroy
terraform apply
```

Grants that duplicate existing manual grants simply merge — LF permissions are additive.

## Step 3 — Acceptance test (the whole point of this PR)

Trigger both silver crawlers and confirm they succeed **without touching the LF console**
(allow up to a few minutes for LF permission propagation, per §5's experience):

```bash
aws glue start-crawler --name lottery-premios-silver-crawler
aws glue start-crawler --name lottery-sorteos-silver-crawler
watch -n 20 'aws glue get-crawler --name lottery-premios-silver-crawler --query Crawler.State; aws glue get-crawler --name lottery-sorteos-silver-crawler --query Crawler.State'
```

Both must reach `READY` again with `LastCrawl.Status == "SUCCEEDED"`:

```bash
aws glue get-crawler --name lottery-premios-silver-crawler --query Crawler.LastCrawl
aws glue get-crawler --name lottery-sorteos-silver-crawler --query Crawler.LastCrawl
```

## Known flakiness

`aws_lakeformation_permissions` resources can show read-back drift when the console
holds broader grants for the same principal/resource than the config declares. If a
re-plan wants to "change" a grant right after apply, compare against
`aws lakeformation list-permissions --principal ...` before assuming a bug; align the
config (or clean the manual grant) rather than apply-looping.

## Rollback

`terraform destroy -target=module.lake_formation` removes the codified grants +
registration (the pre-existing manual grants from §5 are separate entries and survive).
Then `git revert`.

## What this PR touches

- **Adds:** `terraform/modules/lake-formation/{main,variables,outputs}.tf` + README;
  root wiring (`database_name` from `module.catalog`, role from `module.iam`, bucket from
  `module.storage`); root var `enable_iam_allowed_principals_compat` (default true).
- **Edits (legacy, code only):** `lake_formation.tf` (was 100% comments) → pointer.
- **State ops (owner):** none — plain apply.
- **Live change:** the LF registration + grants above (additive; the pipeline's behavior
  is unchanged where manual grants already covered them).
