-- =====================================================================
-- 21_index.sql — S3 / M2 : index choisi, coût de construction et taille
-- Justification : les deux requêtes filtrent par égalité sur store_id ;
-- un B-tree sur store_id est l'index le plus simple qui y répond.
-- =====================================================================
\set ON_ERROR_STOP 1
\timing on
DROP INDEX IF EXISTS benchmark.benchmark_sales_store_id_idx;
CREATE INDEX benchmark_sales_store_id_idx ON benchmark.benchmark_sales (store_id);
\timing off
ANALYZE benchmark.benchmark_sales;
SELECT indexrelid::regclass AS index,
       pg_size_pretty(pg_relation_size(indexrelid)) AS taille_index,
       pg_size_pretty(pg_relation_size(indrelid))   AS taille_table,
       round(100.0 * pg_relation_size(indexrelid) / pg_relation_size(indrelid), 1) AS ratio_pct
FROM pg_index WHERE indrelid = 'benchmark.benchmark_sales'::regclass;
