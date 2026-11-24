-- =====================================================================
-- 20_contexte_volume.sql — S3 / M1 : preuve du volume et conditions de mesure
-- Lecture seule.
-- =====================================================================
\set ON_ERROR_STOP 1
\echo '== Contexte'
SELECT current_database() AS base, split_part(version(), ' ', 2) AS postgresql,
       current_setting('shared_buffers') AS shared_buffers, current_setting('work_mem') AS work_mem,
       current_setting('max_parallel_workers_per_gather') AS workers_par_gather,
       current_setting('jit') AS jit, current_setting('random_page_cost') AS random_page_cost;

\echo '== Volume (attendu : 10 000 000)'
SELECT count(*) AS lignes,
       pg_size_pretty(pg_relation_size('benchmark.benchmark_sales'))       AS taille_table,
       pg_size_pretty(pg_total_relation_size('benchmark.benchmark_sales')) AS taille_totale,
       pg_relation_size('benchmark.benchmark_sales') / current_setting('block_size')::int AS pages
FROM benchmark.benchmark_sales;

\echo '== Index présents sur la table (attendu avant M2 : aucun)'
SELECT indexrelid::regclass AS index, pg_size_pretty(pg_relation_size(indexrelid)) AS taille
FROM pg_index WHERE indrelid = 'benchmark.benchmark_sales'::regclass;

\echo '== Distribution des magasins (fréquences inégales)'
WITH par_magasin AS (            -- grain : 1 ligne = 1 magasin
  SELECT store_id, count(*) AS cnt FROM benchmark.benchmark_sales GROUP BY store_id
)
SELECT CASE WHEN store_id = 1 THEN 'store_id = 1' ELSE 'store_id 2..5001' END AS groupe,
       count(*) AS magasins, sum(cnt) AS ventes,
       round(100.0 * sum(cnt) / sum(sum(cnt)) OVER (), 2) AS part_pct,
       min(cnt) AS min_par_magasin, max(cnt) AS max_par_magasin
FROM par_magasin GROUP BY 1 ORDER BY 1;

\echo '== Filtres retenus et sélectivité réelle'
SELECT 'store_id = 42 (sélectif)' AS filtre, count(*) AS lignes,
       round(100.0 * count(*) / 10000000, 4) AS selectivite_pct
FROM benchmark.benchmark_sales WHERE store_id = 42
UNION ALL
SELECT 'store_id = 1 (large)', count(*), round(100.0 * count(*) / 10000000, 4)
FROM benchmark.benchmark_sales WHERE store_id = 1;

\echo '== Statistiques du planificateur (pg_stats)'
SELECT attname, n_distinct, correlation,
       left(most_common_vals::text, 40) AS mcv_debut, (most_common_freqs)[1:3] AS mcf_3
FROM pg_stats
WHERE schemaname = 'benchmark' AND tablename = 'benchmark_sales'
  AND attname IN ('store_id', 'zone_id', 'channel_id', 'sold_on')
ORDER BY attname;

\echo '== Campagnes : un magasin peut appartenir à plusieurs campagnes'
SELECT store_id, count(*) AS campagnes, array_agg(campaign_id ORDER BY campaign_id) AS campaign_ids
FROM benchmark.campaign_assignments GROUP BY store_id ORDER BY store_id;
