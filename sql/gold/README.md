# `sql/gold/` — Gold layer CTAS definitions (PR-021)

Seven Athena **CTAS** (`CREATE TABLE AS SELECT`) queries that build the Gold
business-metric tables from the **Silver** tables. One file per table:

| File | Table | Grain | Partitioned |
|------|-------|-------|-------------|
| `01_gold_draw_summary.sql` | `gold_draw_summary` | per `numero_sorteo` | no |
| `02_gold_winning_number_frequency.sql` | `gold_winning_number_frequency` | per `numero_premiado` | no |
| `03_gold_terminations.sql` | `gold_terminations` | per 2-digit termination | no |
| `04_gold_letters_distribution.sql` | `gold_letters_distribution` | per `letras` | no |
| `05_gold_geo_winnings.sql` | `gold_geo_winnings` | per `(departamento, ciudad, year)` | **by `year`** |
| `06_gold_vendor_leaderboard.sql` | `gold_vendor_leaderboard` | per `(vendedor, year)` | **by `year`** |
| `07_gold_time_series.sql` | `gold_time_series` | per `(year, month)` | **by `year`** |

**Source of truth:** only the Silver tables `silver_premios_premios` and
`silver_sorteos_sorteos` (the ones the crawlers register in PR-012). Gold never
reads `raw/` or the legacy `processed/` prefix.

## How a CTAS reflects in Athena

A CTAS does three things in one operation:
1. runs the `SELECT` over the Silver tables,
2. writes the result as Parquet to its `external_location`
   (`s3://lottery-partitioned-storage-prod/gold/<name>/`), and
3. **registers the table itself** in the Glue catalog (`lottery_santalucia_db.gold_<name>`).

So — unlike Silver, which needs a crawler to register the table — a Gold table
appears in Athena the moment its CTAS finishes. No crawler required for creation.

## ⚠️ Idempotency contract (important for PR-022)

Each file starts with `DROP TABLE IF EXISTS`. **That is not enough to make a
re-run safe:**

- `DROP TABLE` removes **only** the Glue catalog entry. It does **not** delete
  the Parquet under `external_location`.
- Athena CTAS **fails** if `external_location` already contains files
  (`HIVE_PATH_ALREADY_EXISTS`).

Therefore, to re-run any file you must also empty its S3 prefix first, e.g.:

```bash
aws s3 rm s3://lottery-partitioned-storage-prod/gold/draw_summary/ --recursive
```

### PR-021 (this PR) — manual
The owner runs a couple of these by hand in the Athena console to validate and
pastes row counts into the PR. **After that, those Gold tables and their Parquet
already exist in the account.**

### PR-022 — automation must account for that
When PR-022 wires these into the Step Function, it **must assume the tables may
already exist from the PR-021 manual runs.** Each iteration must, before the CTAS:

1. `DROP TABLE IF EXISTS lottery_santalucia_db.gold_<name>`, **and**
2. empty `s3://.../gold/<name>/`,

**or** switch the pattern to `INSERT INTO` an already-created table. A blind CTAS
against a location that a manual PR-021 run already populated will fail.

## Bucket name

`external_location` hard-codes the real prod bucket
(`lottery-partitioned-storage-prod`) so the files are runnable as-is in PR-021.
PR-022 should parameterize the bucket when it uploads these to S3 and runs them
from the Step Function.
