-- =====================================================================
-- Gold table: gold_draw_summary
-- Grain: one row per numero_sorteo
-- Source: silver_premios_premios + silver_sorteos_sorteos (silver only)
-- =====================================================================
--
-- IDEMPOTENCY CONTRACT (read before re-running):
--   `DROP TABLE IF EXISTS` below removes ONLY the Glue catalog entry.
--   It does NOT delete the Parquet under external_location. Athena CTAS
--   FAILS if external_location already has files (HIVE_PATH_ALREADY_EXISTS).
--   To re-run this file you MUST also empty the S3 prefix first:
--     aws s3 rm s3://lottery-partitioned-storage-prod/gold/draw_summary/ --recursive
--
-- PR-021 (manual): the owner runs this by hand in the Athena console to
--   validate. After a successful run, the table gold_draw_summary and the
--   Parquet at gold/draw_summary/ ALREADY EXIST.
-- PR-022 (automation): the Step Function must assume these tables may
--   already exist from the PR-021 manual runs. Before each CTAS it must
--   DROP TABLE + empty the S3 prefix (or switch to INSERT INTO). A blind
--   CTAS on the same location will fail.
--
-- external_location uses the real prod bucket so this file is runnable
-- as-is in PR-021. PR-022 should parameterize the bucket.
-- =====================================================================

DROP TABLE IF EXISTS lottery_santalucia_db.gold_draw_summary;

CREATE TABLE lottery_santalucia_db.gold_draw_summary
WITH (
  format = 'PARQUET',
  external_location = 's3://lottery-partitioned-storage-prod/gold/draw_summary/'
) AS
SELECT
  s.numero_sorteo                                                       AS numero_sorteo,
  s.tipo_sorteo                                                         AS tipo_sorteo,
  s.fecha_sorteo                                                        AS fecha_sorteo,
  COUNT(p.numero_premiado)                                              AS total_premios,
  COUNT(p.numero_premiado) FILTER (WHERE p.vendedor <> 'NO VENDIDO')    AS premios_vendidos,
  COUNT(p.numero_premiado) FILTER (WHERE p.vendedor =  'NO VENDIDO')    AS premios_no_vendidos,
  ROUND(
    100.0 * COUNT(p.numero_premiado) FILTER (WHERE p.vendedor <> 'NO VENDIDO')
    / NULLIF(COUNT(p.numero_premiado), 0)
  , 2)                                                                  AS pct_vendido,
  SUM(p.monto)                                                          AS total_monto,
  SUM(p.monto) FILTER (WHERE p.vendedor <> 'NO VENDIDO')               AS monto_pagado,
  MAX(p.monto)                                                          AS top_premio
FROM lottery_santalucia_db.silver_sorteos_sorteos s
JOIN lottery_santalucia_db.silver_premios_premios p
  ON p.numero_sorteo = s.numero_sorteo
GROUP BY s.numero_sorteo, s.tipo_sorteo, s.fecha_sorteo;
