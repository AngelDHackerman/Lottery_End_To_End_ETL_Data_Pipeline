-- =====================================================================
-- View: silver_lineage_runs      (PR-045.2, fault F — the queryable half)
-- Grain: one row per (dataset, run_id)  -- the roadmap's grain
-- Source: the silver_lineage VIEW, never the Silver tables directly
-- =====================================================================
--
-- Built on 01_silver_lineage.sql rather than on the two Silver tables, and
-- that is the only interesting decision in this file: two views reading the
-- same tables would be two definitions of what lineage means, free to drift
-- while both look right. This one cannot disagree with the detail view
-- because it has no independent access to the data.
--
-- Answers "what else did that run write?" — the third part of the question
-- this sub-phase exists for. See docs/runbooks/PR-045.2-lineage-queryable.md.
--
-- `source_keys` and `sorteos` are arrays because a run writes one row per
-- sorteo it touched: normally exactly one, but a catch-up run after an outage
-- writes several, and that is precisely when this view gets read.
-- array_agg includes NULLs, so a pre-lineage row reports `source_keys = [NULL]`
-- rather than an empty array. That is honest — the key was never recorded —
-- and it is the one place where a NULL becomes a list element rather than a
-- missing value.

CREATE OR REPLACE VIEW silver_lineage_runs AS
SELECT
    dataset,
    run_id,
    sum(rows_written)                              AS rows_written,
    count(DISTINCT sorteo)                         AS sorteos_written,
    min(first_ingested_at)                         AS first_ingested_at,
    max(last_ingested_at)                          AS last_ingested_at,
    array_sort(array_agg(DISTINCT sorteo))         AS sorteos,
    array_sort(array_agg(DISTINCT source_key))     AS source_keys,
    array_sort(array_agg(DISTINCT parser_version)) AS parser_versions
FROM silver_lineage
GROUP BY dataset, run_id
