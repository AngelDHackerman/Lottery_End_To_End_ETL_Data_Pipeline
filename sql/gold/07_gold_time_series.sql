-- =====================================================================
-- Gold table: gold_time_series   (PARTITIONED BY year)
-- Grain: one row per (year, month)
-- Source: silver_premios_premios + silver_sorteos_sorteos (silver only)
-- =====================================================================
--
-- IDEMPOTENCY: DROP TABLE removes only the catalog entry, not the S3 data.
--   CTAS fails if the location is non-empty. To re-run, first:
--     aws s3 rm s3://lottery-partitioned-storage-prod/gold/time_series/ --recursive
--   PR-021 runs this by hand → the table may already exist for PR-022.
--   PR-022 must DROP + empty the prefix (or INSERT INTO) before each run.
--   See sql/gold/README.md for the full contract.
--
-- Athena CTAS rule: partition columns must be the LAST columns of the
-- SELECT, in the same order as `partitioned_by`. `year` is therefore last.
-- Feeds QuickSight monthly time-series charts.
-- =====================================================================

DROP TABLE IF EXISTS lottery_santalucia_db.gold_time_series;

CREATE TABLE lottery_santalucia_db.gold_time_series
WITH (
  format = 'PARQUET',
  external_location = 's3://lottery-partitioned-storage-prod/gold/time_series/',
  partitioned_by = ARRAY['year']
) AS
SELECT
  MONTH(s.fecha_sorteo)                    AS month,
  COUNT(DISTINCT s.numero_sorteo)          AS num_sorteos,
  COUNT(p.numero_premiado)                 AS num_premios,
  SUM(p.monto)                             AS total_monto,
  YEAR(s.fecha_sorteo)                     AS year
FROM lottery_santalucia_db.silver_sorteos_sorteos s
JOIN lottery_santalucia_db.silver_premios_premios p
  ON p.numero_sorteo = s.numero_sorteo
WHERE s.fecha_sorteo IS NOT NULL
GROUP BY YEAR(s.fecha_sorteo), MONTH(s.fecha_sorteo);
