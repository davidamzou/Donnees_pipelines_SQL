-- =====================================================================
-- 22_estimations.sql — S3 / M3 (A1) : écart estimé / réel
-- zone_id et channel_id valent tous deux 1 + n % 10 : ils sont parfaitement
-- corrélés. Le planificateur suppose l'indépendance et multiplie les
-- sélectivités (0,1 x 0,1 = 1 %), d'où une erreur d'un facteur 10.
-- La correction (statistiques étendues) est testée puis ANNULÉE (ROLLBACK)
-- pour ne pas modifier l'état de référence.
-- =====================================================================
\set ON_ERROR_STOP 1
\echo '== Sans statistiques étendues : zone 3 ET canal 3 (combinaison qui existe)'
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) FROM benchmark.benchmark_sales WHERE zone_id = 3 AND channel_id = 3;
\echo '== Sans statistiques étendues : zone 3 ET canal 4 (combinaison qui n''existe pas)'
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) FROM benchmark.benchmark_sales WHERE zone_id = 3 AND channel_id = 4;

BEGIN;
CREATE STATISTICS benchmark.sales_zone_channel (dependencies, mcv) ON zone_id, channel_id
  FROM benchmark.benchmark_sales;
ANALYZE benchmark.benchmark_sales;
\echo '== Avec statistiques étendues (dependencies, mcv) : zone 3 ET canal 3'
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) FROM benchmark.benchmark_sales WHERE zone_id = 3 AND channel_id = 3;
\echo '== Avec statistiques étendues : zone 3 ET canal 4'
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) FROM benchmark.benchmark_sales WHERE zone_id = 3 AND channel_id = 4;
ROLLBACK;
ANALYZE benchmark.benchmark_sales;
