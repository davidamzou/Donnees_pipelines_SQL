-- Filtre très sélectif : 1 magasin parmi 5 000 « petits » (100 lignes / 10 M).
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) AS ventes, sum(amount_cents) AS montant_cents
FROM benchmark.benchmark_sales
WHERE store_id = 42;
