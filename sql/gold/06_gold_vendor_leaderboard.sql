-- =====================================================================
-- Gold table: gold_vendor_leaderboard   (PARTITIONED BY year)
-- Grain: one row per vendedor per year
-- Source: silver_premios_premios + silver_sorteos_sorteos (silver only)
-- =====================================================================
--
-- IDEMPOTENCY: DROP TABLE removes only the catalog entry, not the S3 data.
--   CTAS fails if the location is non-empty. To re-run, first:
--     aws s3 rm s3://lottery-partitioned-storage-prod/gold/vendor_leaderboard/ --recursive
--   PR-021 runs this by hand → the table may already exist for PR-022.
--   PR-022 must DROP + empty the prefix (or INSERT INTO) before each run.
--   See sql/gold/README.md for the full contract.
--
-- Athena CTAS rule: partition columns must be the LAST columns of the
-- SELECT, in the same order as `partitioned_by`. `year` is therefore last.
-- 'NO VENDIDO' is excluded — it is the absence of a vendor, not a seller.
-- =====================================================================

-- ⚠️ PR-042.1 CHANGED HOW THIS FILE IS RUN BY THE PIPELINE.
--   The Step Function no longer executes this file as written. Its Lambda reads it, rewrites
--   the CREATE below to build a STAGING table at a per-run location
--   (gold/<name>/run=<execution>/), and only after Athena succeeds does it point the
--   published table at that generation. Nothing published is dropped or emptied at any
--   point, which is what removed the seven-day hole a failed CTAS used to leave.
--   So: the DROP below is NOT what the pipeline runs, and external_location below is the
--   table's FAMILY prefix, not where the current generation lives. The file remains the
--   single source of truth for the table name, the target prefix and the SELECT — the
--   Lambda derives everything else from it.
--   Running this file BY HAND in the Athena console still works and still needs the old
--   ritual (empty the prefix first), but it publishes a table outside the generation scheme
--   — use it to check a query, not to publish.

DROP TABLE IF EXISTS lottery_santalucia_db.gold_vendor_leaderboard;

CREATE TABLE lottery_santalucia_db.gold_vendor_leaderboard
WITH (
  format = 'PARQUET',
  external_location = 's3://lottery-partitioned-storage-prod/gold/vendor_leaderboard/',
  partitioned_by = ARRAY['year']
) AS
SELECT
  p.vendedor               AS vendedor,
  COUNT(*)                 AS num_premios,
  SUM(p.monto)             AS total_monto,
  YEAR(s.fecha_sorteo)     AS year
FROM lottery_santalucia_db.silver_premios_premios p
JOIN lottery_santalucia_db.silver_sorteos_sorteos s
  ON p.numero_sorteo = s.numero_sorteo
WHERE p.vendedor IS NOT NULL
  AND p.vendedor <> 'NO VENDIDO'
  AND s.fecha_sorteo IS NOT NULL
GROUP BY p.vendedor, YEAR(s.fecha_sorteo);
