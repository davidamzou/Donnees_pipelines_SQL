-- =====================================================================
-- 23_multiplication.sql — S3 / M3 : jointure qui multiplie les lignes
-- campaign_assignments a pour grain (magasin, campagne). Le magasin 42 est
-- dans 2 campagnes : joindre les ventes à cette table duplique ses ventes.
-- =====================================================================
\set ON_ERROR_STOP 1
\echo '== Jointure naïve : total des ventes « en campagne » (FAUX)'
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) AS lignes, sum(s.amount_cents) AS montant_cents
FROM benchmark.benchmark_sales s
JOIN benchmark.campaign_assignments ca USING (store_id);

\echo '== Résultats comparés'
SELECT 'jointure naïve (grain vente x campagne)' AS methode,
       count(*) AS lignes, sum(s.amount_cents) AS montant_cents
FROM benchmark.benchmark_sales s JOIN benchmark.campaign_assignments ca USING (store_id)
UNION ALL
SELECT 'semi-jointure EXISTS (grain vente)', count(*), sum(s.amount_cents)
FROM benchmark.benchmark_sales s
WHERE EXISTS (SELECT 1 FROM benchmark.campaign_assignments ca WHERE ca.store_id = s.store_id)
UNION ALL
SELECT 'magasin 42 seul', count(*), sum(amount_cents)
FROM benchmark.benchmark_sales WHERE store_id = 42;

\echo '== Par campagne : ici le grain (vente, campagne) est VOULU, mais les totaux ne s''additionnent pas'
SELECT ca.campaign_id, count(*) AS ventes, sum(s.amount_cents) AS montant_cents,
       array_agg(DISTINCT ca.store_id) AS magasins
FROM benchmark.benchmark_sales s JOIN benchmark.campaign_assignments ca USING (store_id)
GROUP BY ca.campaign_id ORDER BY ca.campaign_id;

\echo '== Plan de la version correcte (semi-jointure)'
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*), sum(s.amount_cents)
FROM benchmark.benchmark_sales s
WHERE EXISTS (SELECT 1 FROM benchmark.campaign_assignments ca WHERE ca.store_id = s.store_id);
