-- =====================================================================
-- Gold table: gold_geo_winnings   (PARTITIONED BY year)
-- Grain: one row per (departamento, ciudad) per year
-- Source: silver_premios_premios + silver_sorteos_sorteos (silver only)
-- =====================================================================
--
-- IDEMPOTENCY: DROP TABLE removes only the catalog entry, not the S3 data.
--   CTAS fails if the location is non-empty. To re-run, first:
--     aws s3 rm s3://lottery-partitioned-storage-prod/gold/geo_winnings/ --recursive
--   PR-021 runs this by hand → the table may already exist for PR-022.
--   PR-022 must DROP + empty the prefix (or INSERT INTO) before each run.
--   See sql/gold/README.md for the full contract.
--
-- Athena CTAS rule: partition columns must be the LAST columns of the
-- SELECT, in the same order as `partitioned_by`. `year` is therefore last.
-- =====================================================================

DROP TABLE IF EXISTS lottery_santalucia_db.gold_geo_winnings;

CREATE TABLE lottery_santalucia_db.gold_geo_winnings
WITH (
  format = 'PARQUET',
  external_location = 's3://lottery-partitioned-storage-prod/gold/geo_winnings/',
  partitioned_by = ARRAY['year']
) AS
SELECT
  p.departamento           AS departamento,
  p.ciudad                 AS ciudad,
  COUNT(*)                 AS num_ganadores,
  SUM(p.monto)             AS total_monto,
  YEAR(s.fecha_sorteo)     AS year
FROM lottery_santalucia_db.silver_premios_premios p
JOIN lottery_santalucia_db.silver_sorteos_sorteos s
  ON p.numero_sorteo = s.numero_sorteo
WHERE p.vendedor <> 'NO VENDIDO'
  AND s.fecha_sorteo IS NOT NULL
GROUP BY p.departamento, p.ciudad, YEAR(s.fecha_sorteo);
