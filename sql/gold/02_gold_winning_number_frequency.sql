-- =====================================================================
-- Gold table: gold_winning_number_frequency
-- Grain: one row per numero_premiado (4-digit winning number)
-- Source: silver_premios_premios (silver only)
-- =====================================================================
--
-- IDEMPOTENCY: DROP TABLE removes only the catalog entry, not the S3 data.
--   CTAS fails if the location is non-empty. To re-run, first:
--     aws s3 rm s3://lottery-partitioned-storage-prod/gold/winning_number_frequency/ --recursive
--   PR-021 runs this by hand → the table may already exist for PR-022.
--   PR-022 must DROP + empty the prefix (or INSERT INTO) before each run.
--   See sql/gold/README.md for the full contract.
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

DROP TABLE IF EXISTS lottery_santalucia_db.gold_winning_number_frequency;

CREATE TABLE lottery_santalucia_db.gold_winning_number_frequency
WITH (
  format = 'PARQUET',
  external_location = 's3://lottery-partitioned-storage-prod/gold/winning_number_frequency/'
) AS
SELECT
  p.numero_premiado          AS numero_premiado,
  COUNT(*)                   AS veces_ganador,
  SUM(p.monto)               AS total_monto,
  MAX(p.monto)               AS max_monto
FROM lottery_santalucia_db.silver_premios_premios p
WHERE p.numero_premiado IS NOT NULL
GROUP BY p.numero_premiado;
