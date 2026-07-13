# Module: `lake-formation`

Lake Formation resource registration + permissions so the silver crawlers run without
manual console clicks.

**Status:** codified in **PR-013**. Unlike the other modules these are **new** resources,
not imports — the equivalent setup existed only as console clicks (documented in
`challanges_faced.md` §5). See `docs/runbooks/PR-013-lake-formation.md`.

## What it grants

| Resource | Principal | Permissions |
|---|---|---|
| `s3://<partitioned>/silver` | (registration) | via `AWSServiceRoleForLakeFormationDataAccess` |
| database | `glue-crawler-role` | `CREATE_TABLE, ALTER, DROP, DESCRIBE` |
| all tables in db | `glue-crawler-role` | `ALTER, DELETE, DESCRIBE, DROP, INSERT, SELECT` |
| silver data location | `glue-crawler-role` | `DATA_LOCATION_ACCESS` |
| database | `IAM_ALLOWED_PRINCIPALS` | `CREATE_TABLE, ALTER, DROP, DESCRIBE` (gated) |

The `IAM_ALLOWED_PRINCIPALS` grant is gated behind
`enable_iam_allowed_principals_compat` (default **true**). It is required while the
account runs LF **Hybrid access mode** (Glue's default IAM fallback). Disable it only
when the account moves to full LF enforcement.

## Two gotchas this module deliberately avoids (PR-013a)

**1. Never write `permissions = ["ALL"]`.** Lake Formation expands `ALL` (Super)
server-side into the six table permissions, then reads them back expanded. A config
saying `["ALL"]` therefore never matches its own read-back, and Terraform wants to
**replace the grant on every plan, forever** — revoking and re-granting the crawler's
access on each apply. Enumerating the six permissions is equivalent and stable. (This
bites in a fresh account too; it is not an artifact of any one environment.)

**2. No `permissions_with_grant_option`.** A grant option lets a principal *re-grant* a
permission to other principals. The crawler only reads S3 and writes table metadata — it
never delegates — so grant options would be privilege with no use case. The original
console-era setup had them; PR-013a revoked them so Terraform's declaration is the whole
truth. If `terraform plan` ever shows an unexplained grant diff, check for permissions
added by hand:

```bash
aws lakeformation list-permissions \
  --principal DataLakePrincipalIdentifier=<crawler-role-arn> \
  --resource '{"Table":{"DatabaseName":"lottery_santalucia_db","TableWildcard":{}}}'
```

## Inputs / outputs

- Inputs: `partitioned_bucket_arn`, `glue_crawler_role_arn`, `database_name`,
  `enable_iam_allowed_principals_compat`.
- Outputs: `silver_location_arn`.

## Acceptance

`terraform apply` + manually triggering both silver crawlers must succeed with **no**
Lake Formation console clicks (allow a few minutes for LF permission propagation).
