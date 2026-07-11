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
| all tables in db | `glue-crawler-role` | `ALL` (Super — matches the manual grant) |
| silver data location | `glue-crawler-role` | `DATA_LOCATION_ACCESS` |
| database | `IAM_ALLOWED_PRINCIPALS` | `CREATE_TABLE, ALTER, DROP, DESCRIBE` (gated) |

The `IAM_ALLOWED_PRINCIPALS` grant is gated behind
`enable_iam_allowed_principals_compat` (default **true**). It is required while the
account runs LF **Hybrid access mode** (Glue's default IAM fallback). Disable it only
when the account moves to full LF enforcement.

## Inputs / outputs

- Inputs: `partitioned_bucket_arn`, `glue_crawler_role_arn`, `database_name`,
  `enable_iam_allowed_principals_compat`.
- Outputs: `silver_location_arn`.

## Acceptance

`terraform apply` + manually triggering both silver crawlers must succeed with **no**
Lake Formation console clicks (allow a few minutes for LF permission propagation).
