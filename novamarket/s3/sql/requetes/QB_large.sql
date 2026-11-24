-- Filtre peu sélectif : le magasin 1 porte 95 % des lignes (9,5 M / 10 M).
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) AS ventes, sum(amount_cents) AS montant_cents
FROM benchmark.benchmark_sales
WHERE store_id = 1;
