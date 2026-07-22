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
