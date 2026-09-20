-- =====================================================================
-- Gold table: gold_terminations
-- Grain: one row per last-2-digit termination ("terminación")
-- Source: silver_premios_premios (silver only)
-- =====================================================================
--
-- IDEMPOTENCY: DROP TABLE removes only the catalog entry, not the S3 data.
--   CTAS fails if the location is non-empty. To re-run, first:
--     aws s3 rm s3://lottery-partitioned-storage-prod/gold/terminations/ --recursive
--   PR-021 runs this by hand → the table may already exist for PR-022.
--   PR-022 must DROP + empty the prefix (or INSERT INTO) before each run.
--   See sql/gold/README.md for the full contract.
--
-- termination = last 2 digits of numero_premiado, zero-padded so 7 -> '07',
-- 109964 -> '64'. `% 100` is length-robust: the real numero_premiado ranges
-- 1..109964 (1 to 6 digits, verified against silver), NOT a fixed 4-digit number,
-- so a fixed-width LPAD/SUBSTR would slice the wrong two digits.
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

DROP TABLE IF EXISTS lottery_santalucia_db.gold_terminations;

CREATE TABLE lottery_santalucia_db.gold_terminations
WITH (
  format = 'PARQUET',
  external_location = 's3://lottery-partitioned-storage-prod/gold/terminations/'
) AS
SELECT
  LPAD(CAST(p.numero_premiado % 100 AS VARCHAR), 2, '0')  AS terminacion,
  COUNT(*)                                                AS veces_ganador,
  SUM(p.monto)                                            AS total_monto
FROM lottery_santalucia_db.silver_premios_premios p
WHERE p.numero_premiado IS NOT NULL
GROUP BY LPAD(CAST(p.numero_premiado % 100 AS VARCHAR), 2, '0');
