# `sql/lineage/` — the Silver lineage views (PR-045.2)

Two Athena **views** that make PR-045.1's lineage columns answerable as a query.
One file per view, created by `make lineage-views`:

| File | View | Grain |
|------|------|-------|
| `01_silver_lineage.sql` | `silver_lineage` | one row per `(dataset, run_id, year, sorteo, source_key)` |
| `02_silver_lineage_runs.sql` | `silver_lineage_runs` | one row per `(dataset, run_id)` |

The second reads the **first**, not the Silver tables. Two views over the same
tables would be two definitions of what lineage means, each free to drift while
both look right.

## The question these exist for

> *"Sorteo 3134 looks wrong — which run wrote it, from which raw file, and what
> else did that run write?"*

```sql
SELECT * FROM silver_lineage_runs WHERE contains(sorteos, '3134');
```

One query, three answers: `run_id`, `source_keys`, and the full `sorteos` list —
everything else that run touched. Real output is pasted into
`docs/runbooks/PR-045.2-lineage-queryable.md`.

## How these differ from `sql/gold/`

| | `sql/gold/` | `sql/lineage/` |
|---|---|---|
| What it creates | seven **tables**, via CTAS | two **views** |
| Who runs it | the Step Function, every Thursday | a person, when the SQL changes |
| Uploaded to S3 | yes, `s3://<partitioned>/sql/gold/` by Terraform | no |
| Idempotency ritual | `DROP TABLE` **and** empty the S3 prefix | none — `CREATE OR REPLACE VIEW` |
| Statements per file | two (`DROP` + `CREATE`) | **one** (Athena takes one per execution) |

A view stores no data, so there is no prefix to empty and no generation to
promote. It also costs nothing to hold and nothing to rebuild: a view is catalog
metadata, and creating one scans 0 bytes.

Terraform globs `sql/gold/*.sql` only (`fileset(local.gold_sql_dir, "*.sql")`),
so nothing here is picked up by the gold Map state.

## Why the views are not in Terraform, when the Silver tables now are

An Athena view is stored in Glue as a base64 blob of Athena's internal JSON —
`/* Presto View: eyJvcmlnaW5hbFNxbCI6... */` — holding the SQL *and* a column
list that must agree with it. Declaring that in Terraform means hand-maintaining
an undocumented serialisation, and it drifts: the views already in this account
carry `isProtected` and `isMultiDialect` keys that the widely copied Terraform
examples do not have.

A table's schema is ours to declare, so `silver_sorteos_sorteos`,
`silver_premios_premios` and `quarantine_rejects` live in
`terraform/modules/catalog/main.tf`. A view's *encoding* is Athena's, so Athena
writes it and this directory owns the SQL that produced it.

## Pre-lineage rows

The four lineage columns exist only on Silver files written after PR-045.1 was
deployed (2026-09-27). Everything older reports `run_id NULL`, and
`silver_lineage_runs` therefore carries one row per dataset with a NULL `run_id`
covering the whole archive. That is correct: NULL means *written before lineage
existed*, and it is deliberately not backfilled — a fabricated `run_id` would
claim a provenance nobody recorded.
