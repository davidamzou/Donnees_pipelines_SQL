# NovaMarket S3 — Solution : benchmark, index et analyse critique

Rejouer depuis `novamarket/` :

```bash
docker compose exec -T postgres psql -X -v ON_ERROR_STOP=1 -U atelier -d novamarket < s3/generer.sql
./s3/sql/run_s3.sh
```

`run_s3.sh` supprime l'index s'il existe, puis mesure la référence sans index, crée l'index, refait les mesures et lance les analyses M3. Toutes les sorties sont dans [`s3/resultats/`](resultats/) :

| Fichier | Contenu |
| --- | --- |
| `00_generation.txt` | sortie de `generer.sql` (`COMMIT`, 8,9 s pour 10 M lignes) |
| `20_contexte_volume.txt` | paramètres PostgreSQL, volume, tailles, distribution, `pg_stats` |
| `21_index.txt` | `CREATE INDEX` chronométré, taille de l'index |
| `plans/*.txt` | **plans complets** `EXPLAIN (ANALYZE, BUFFERS)` de chaque passage |
| `mesures.csv` | une ligne par passage : temps, planification, tampons, nœud |
| `synthese.md` | tableau des médianes (généré par `synthese.py`) |
| `22_estimations.txt`, `23_multiplication.txt` | analyses M3 / A1 |

Le jeu `benchmark` est indépendant des ventes NovaMarket. Aucun chiffre de cette page ne s'ajoute aux indicateurs S1–S2.

---

## M1 — Mise en place et référence sans index

### Conditions de mesure

| Élément | Valeur |
| --- | --- |
| Poste | macOS, Docker Desktop, conteneur limité à 2 CPU / 2 Go (`compose.yaml`) |
| PostgreSQL | 17.12, paramètres par défaut : `shared_buffers = 128MB`, `work_mem = 4MB`, `max_parallel_workers_per_gather = 2`, `jit = on`, `random_page_cost = 4` |
| Données | `benchmark.benchmark_sales` : **10 000 000 lignes**, 498 Mo, 63 744 pages de 8 Ko, aucun index au départ |
| Protocole | pour chaque requête : redémarrage de PostgreSQL (tampons partagés vidés), **1er passage isolé**, puis **3 répétitions**. On retient la **médiane des répétitions** |

### Distribution et filtres choisis

| Filtre | Lignes | Sélectivité | Rôle |
| --- | ---: | ---: | --- |
| `store_id = 42` | 100 | 0,001 % | filtre **très sélectif** (un des 5 000 « petits » magasins) |
| `store_id = 1` | 9 500 000 | 95 % | filtre **peu sélectif** (le magasin 1 porte 95 % des ventes) |

Requête mesurée (même forme pour les deux filtres, [`requetes/`](sql/requetes/)) :

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) AS ventes, sum(amount_cents) AS montant_cents
FROM benchmark.benchmark_sales
WHERE store_id = 42;   -- ou 1
```

Sans index, les deux requêtes font un `Parallel Seq Scan` (2 workers + leader) et lisent les 63 744 pages. Pour `store_id = 42`, 9 999 900 lignes sont lues puis jetées (`Rows Removed by Filter: 3333300` par processus) pour en garder 100.

---

## M2 — Optimisation par index

### Index choisi

```sql
CREATE INDEX benchmark_sales_store_id_idx ON benchmark.benchmark_sales (store_id);
```

Les deux requêtes filtrent par égalité sur `store_id`. Un B-tree simple sur cette colonne répond au besoin. Un index couvrant `(store_id) INCLUDE (amount_cents)` permettrait un *index-only scan*, mais il serait plus gros, et le gain sur 100 lignes est négligeable.

| Coût de l'index | Valeur |
| --- | --- |
| Temps de construction | **1,5 s** (2,1 s lors d'un premier essai) |
| Taille | **66 Mo**, soit 13,3 % de la table |
| Coût en écriture | chaque `INSERT`/`UPDATE` de `store_id` doit aussi mettre l'index à jour (non mesuré ici, la table est en lecture seule) |

### Tableau de mesures

Les temps viennent de `Execution Time` en ms. La colonne tampons indique `shared hit / read` sur le nœud racine. Source : [`resultats/synthese.md`](resultats/synthese.md).

| Phase | Requête | Plan | 1er passage | Répétitions | **Médiane** | Tampons hit / read |
| --- | --- | --- | ---: | --- | ---: | --- |
| sans index | `store_id = 42` | Parallel Seq Scan | 113,0 | 137,4 / 146,5 / 111,3 | **137,4** | 96 / 63 648 |
| sans index | `store_id = 1` | Parallel Seq Scan | 447,1 | 441,0 / 411,9 / 448,0 | **441,0** | 96 / 63 648 |
| avec index | `store_id = 42` | **Index Scan** | 1,20 | 0,17 / 0,14 / 0,20 | **0,17** | 103 / 0 |
| avec index | `store_id = 1` | Parallel Seq Scan (index **ignoré**) | 682,0 | 553,2 / 508,5 / 479,8 | **508,5** | 192 / 63 552 |
| avec index, scan séquentiel interdit | `store_id = 1` | Parallel Bitmap Heap Scan | 697,5 | 678,3 / 822,9 / 787,6 | **787,6** | 0 / 71 694 |

### Commentaire de résultat

- **Filtre sélectif** : le temps passe de 137 ms à 0,17 ms, soit environ **800 fois plus rapide**. On lit 103 pages (3 pages d'index et environ 100 pages de table, une par vente) au lieu de 63 744. L'index est rentable dès la première requête : 1,5 s de construction équivalent à une dizaine d'exécutions sans index.
- **Filtre peu sélectif** : le planificateur **ignore l'index**, à raison. Le plan reste un `Parallel Seq Scan`, avec le même nombre de pages lues avant et après. L'écart de médiane (441 → 508 ms) ne vient donc pas de l'index : c'est la variabilité du poste, puisque les répétitions vont de 412 à 553 ms pour un plan identique. **Un index présent n'est pas un index utilisé.**

---

## M3 — Analyse critique

### 1. Dégradation par un index mal employé (cas d'index inefficace)

Quand on force l'usage de l'index sur `store_id = 1` (`SET enable_seqscan = off`), le plan devient un `Bitmap Index Scan` suivi d'un `Bitmap Heap Scan`. La médiane passe de **508 ms à 788 ms (+55 %)**, et les pages lues de 63 552 à **71 694**. Il faut lire 7 999 pages d'index pour retrouver 9,5 M d'entrées, **en plus** de la totalité des 21 466 × 3 pages de table, puisque 95 % des lignes sont réparties partout. L'index ajoute du travail sans rien éviter.

C'est la dégradation attendue (cas « A10 » du livret) : avec une **faible sélectivité**, l'index ne fait que s'ajouter à la lecture complète. Le planificateur l'a correctement évité. C'est un problème de **plan**, pas de données.

### 2. Écarts entre cardinalités estimées et réelles

| Requête | Estimé | Réel | Cause |
| --- | ---: | ---: | --- |
| `store_id = 42`, avant index | 152 × 3 = 456 | 100 | `n_distinct(store_id)` estimé à **1 301** au lieu de 5 001. L'échantillon d'`ANALYZE` (30 000 lignes) ne voit qu'une partie des 5 000 petits magasins |
| `store_id = 42`, avec index | 375 | 100 | même cause, après un nouvel `ANALYZE` (échantillon différent) |
| jointure campagnes, par magasin | 7 519 | 100 | même cause, amplifiée par la jointure : 15 782 lignes estimées pour 400 réelles |
| `zone_id = 3 AND channel_id = 3` | 43 098 × 3 ≈ 129 000 | **1 000 000** | colonnes **parfaitement corrélées** (`1 + n % 10` toutes les deux) alors que le planificateur suppose l'indépendance : 0,1 × 0,1 = 1 % au lieu de 10 % |
| `zone_id = 3 AND channel_id = 4` | ≈ 128 000 | **0** | même cause : la combinaison n'existe jamais |

**Correction testée** ([`22_estimations.sql`](sql/22_estimations.sql), annulée par `ROLLBACK`) : `CREATE STATISTICS … (dependencies, mcv) ON zone_id, channel_id` puis `ANALYZE`. Les estimations deviennent 412 635 × 3 ≈ **1,24 M** (réel 1 M) et **1** (réel 0). Le plan ne change pas ici : un scan complet reste le meilleur choix pour 10 % de la table. En revanche, une estimation 10 fois trop basse peut fausser un plan de jointure en aval (boucle imbriquée choisie à tort). Ces écarts sont des limites des **statistiques**, pas des erreurs dans les données. On peut augmenter `ALTER TABLE … ALTER COLUMN store_id SET STATISTICS 1000` pour mieux estimer `n_distinct`.

### 3. Lecture des `BUFFERS` et limites du cache

- Le scan séquentiel affiche toujours environ 63 600 pages en **`read`**, même au 3ᵉ passage. La table (498 Mo) dépasse `shared_buffers` (128 Mo), et PostgreSQL lit les grandes tables par un petit anneau de tampons pour ne pas vider son cache. Ces lectures sont en réalité servies par le **cache du système** de la VM Docker : un `read` n'est pas forcément un accès disque. Le temps est donc dominé par la copie mémoire et le filtrage CPU de 10 M lignes.
- L'index scan passe de 103 `read` au 1er passage à 103 `hit` ensuite : les 103 pages tiennent dans `shared_buffers`. C'est l'effet du **1er passage**, isolé dans les mesures (1,20 ms contre 0,17 ms).
- Le redémarrage vide les tampons de PostgreSQL mais pas le cache de la VM. On ne mesure donc jamais un vrai démarrage « à froid » depuis le disque.
- Le poste (portable, Docker Desktop, autres applications) produit une variance de ±15 % sur les scans longs. Seuls les écarts d'un ordre de grandeur (×800) sont concluants. Les écarts de 10 à 20 % entre deux scans séquentiels ne le sont pas.
- `JIT` est actif sur les scans complets (environ 8 ms de compilation, visible dans les plans) : c'est un coût fixe inclus dans les temps.

### 4. Jointure qui multiplie les lignes

`campaign_assignments` a pour grain (magasin, campagne), et le magasin 42 appartient à deux campagnes (101 et 102). [`23_multiplication.sql`](sql/23_multiplication.sql) :

| Méthode | Lignes | Montant (centimes) |
| --- | ---: | ---: |
| jointure naïve `JOIN campaign_assignments` | 400 | 5 246 000 |
| semi-jointure `WHERE EXISTS (…)` | **300** | **4 236 000** |
| écart = ventes du magasin 42 comptées deux fois | 100 | 1 010 000 |

La jointure naïve n'a pas d'erreur de **données** ni de **plan** : c'est une erreur de **grain**. Le résultat est au grain (vente × campagne), alors que la question porte sur des ventes. Pour « les ventes des magasins en campagne », on utilise `EXISTS`. Pour « les ventes par campagne », le grain (vente, campagne) est voulu, mais les totaux par campagne ne s'additionnent pas (200 + 100 + 100 = 400 ≠ 300). On trouve le même phénomène en S2 avec le doublon du produit 3 (833 lignes au lieu de 800).

---

## Conclusion

L'index B-tree sur `store_id` est **justifié** : il coûte 66 Mo et 1,5 s de construction, et rend la recherche d'un magasin environ 800 fois plus rapide. Il n'apporte **rien** pour le magasin 1, et l'imposer coûte 55 % de temps en plus. Le planificateur fait seul le bon choix tant que ses statistiques sont correctes. Les écarts estimé/réel observés (`n_distinct`, colonnes corrélées) montrent la limite de ce choix.
