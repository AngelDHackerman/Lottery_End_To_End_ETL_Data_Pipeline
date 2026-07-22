-- =====================================================================
-- Gold table: gold_letters_distribution
-- Grain: one row per letras combination
-- Source: silver_premios_premios (silver only)
-- =====================================================================
--
-- IDEMPOTENCY: DROP TABLE removes only the catalog entry, not the S3 data.
--   CTAS fails if the location is non-empty. To re-run, first:
--     aws s3 rm s3://lottery-partitioned-storage-prod/gold/letters_distribution/ --recursive
--   PR-021 runs this by hand → the table may already exist for PR-022.
--   PR-022 must DROP + empty the prefix (or INSERT INTO) before each run.
--   See sql/gold/README.md for the full contract.
-- =====================================================================

DROP TABLE IF EXISTS lottery_santalucia_db.gold_letters_distribution;

CREATE TABLE lottery_santalucia_db.gold_letters_distribution
WITH (
  format = 'PARQUET',
  external_location = 's3://lottery-partitioned-storage-prod/gold/letters_distribution/'
) AS
SELECT
  p.letras           AS letras,
  COUNT(*)           AS veces_ganador,
  SUM(p.monto)       AS total_monto
FROM lottery_santalucia_db.silver_premios_premios p
WHERE p.letras IS NOT NULL
GROUP BY p.letras;
