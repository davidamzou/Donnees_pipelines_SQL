-- Dégradation : même requête large, mais on INTERDIT le scan séquentiel pour
-- forcer l'usage de l'index (simulation d'un « index toujours meilleur »).
SET enable_seqscan = off;
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) AS ventes, sum(amount_cents) AS montant_cents
FROM benchmark.benchmark_sales
WHERE store_id = 1;
