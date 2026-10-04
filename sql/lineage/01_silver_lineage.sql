-- =====================================================================
-- View: silver_lineage           (PR-045.2, fault F — the queryable half)
-- Grain: one row per (dataset, run_id, year, sorteo, source_key)
-- Source: silver_sorteos_sorteos + silver_premios_premios
-- =====================================================================
--
-- A VIEW, not an eighth gold table. This is metadata about writes, not
-- analytics: it is read when something looks wrong, which is a handful of
-- times a year, and materialising it would add a CTAS to the weekly Step
-- Function to precompute an answer nobody is waiting for.
--
-- WHY THIS IS NOT IN TERRAFORM, when PR-044.2 put the quarantine TABLE there.
--   An Athena view is stored in Glue as a base64 blob of Athena's own internal
--   JSON (`/* Presto View: eyJvcmlnaW5hbFNxbCI6... */`), listing the SQL *and*
--   a column list that must agree with it. Declaring that by hand means
--   hand-maintaining an undocumented serialisation: the views already in this
--   account carry `isProtected` and `isMultiDialect` keys that the widely
--   copied Terraform templates do not have, which is what that format drifting
--   under you looks like. The table's schema is ours to declare; a view's
--   encoding is Athena's. So Athena writes the blob and we own the SQL.
--   Recreating either view is one command: `make lineage-views`.
--
-- The table names are UNQUALIFIED: the database comes from the query's
-- execution context, which scripts/create_lineage_views.sh sets from one
-- place. Running this by hand in the console means selecting
-- lottery_santalucia_db first.
--
-- Run by scripts/create_lineage_views.sh. ONE statement per file: Athena's
-- StartQueryExecution takes exactly one, and CREATE OR REPLACE needs no DROP,
-- so the gold layer's idempotency ritual does not apply here.
--
-- ⚠️ The four lineage columns only exist on Silver files written after
-- PR-045.1 was deployed (2026-09-27). Everything older reports run_id NULL,
-- which is correct and deliberate: NULL means "written before lineage
-- existed". It is not a gap to be backfilled — see the runbook §6.

CREATE OR REPLACE VIEW silver_lineage AS
SELECT
    'sorteos'        AS dataset,
    run_id,
    parser_version,
    year,
    sorteo,
    source_key,
    count(*)         AS rows_written,
    min(ingested_at) AS first_ingested_at,
    max(ingested_at) AS last_ingested_at
FROM silver_sorteos_sorteos
GROUP BY run_id, parser_version, year, sorteo, source_key
UNION ALL
SELECT
    'premios'        AS dataset,
    run_id,
    parser_version,
    year,
    sorteo,
    source_key,
    count(*)         AS rows_written,
    min(ingested_at) AS first_ingested_at,
    max(ingested_at) AS last_ingested_at
FROM silver_premios_premios
GROUP BY run_id, parser_version, year, sorteo, source_key
