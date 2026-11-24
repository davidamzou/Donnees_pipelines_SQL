# NovaMarket S2 — Solution : catalogue et SQL avancé

Rejouer depuis `novamarket/` (base S1 déjà chargée par `./s1/sql/run_all.sh`) :

```bash
./s2/sql/run_s2.sh
```

Le script copie `s2/donnees/` dans le conteneur (`/tmp/novamarket-s2`), exécute les scripts dans l'ordre et écrit chaque sortie dans [`s2/resultats/`](resultats/). Il est rejouable : `10_catalogue.sql` ne supprime et ne recrée que les objets du catalogue. Les tables de ventes S1 ne sont pas modifiées. Seule une clé étrangère `order_items.product_id → products` leur est ajoutée.

| Script | Mission |
| --- | --- |
| [`10_catalogue.sql`](sql/10_catalogue.sql) | M1 : DDL, réception brute, contrôles, intégration, rejets, clé étrangère |
| [`11_controles_catalogue.sql`](sql/11_controles_catalogue.sql) | M1 : multiplicités, couverture, cohérence des dates, risque de multiplication |
| [`12_classements.sql`](sql/12_classements.sql) | M2 : `RANK` / `DENSE_RANK` / `ROW_NUMBER`, effet d'une duplication |
| [`13_evolution.sql`](sql/13_evolution.sql) | M3 : `LAG` / `LEAD`, couverture des périodes, ventes avant mise en vente |
| [`14_segmentation.sql`](sql/14_segmentation.sql) | M4 / A1 : `NTILE(4)` et ex æquo |
| [`15_hierarchie.sql`](sql/15_hierarchie.sql) | M5 / A1 : `WITH RECURSIVE`, cycles, CA consolidé par branche |

**Périmètre de vente commun** à toutes les analyses : commandes `status = 'completed'`, montant = `quantity × unit_price_cents` (prix de la transaction). Ce périmètre donne le CA S1 de **26 210,00 €**. Chaque script le vérifie.

---

## M1 — Intégration du catalogue

### Grain et relations

| Source | Grain (1 ligne =) | Identifiant | Référence vers |
| --- | --- | --- | --- |
| categories.csv | une catégorie | `category_id` | parent (`parent_category_id`, vide pour une racine) |
| products.csv | une fiche produit **reçue** | `product_id`, unicité à contrôler ; `sku` unique attendu | catégorie (`category_id`) |

- 1 catégorie → N sous-catégories (auto-référence) ; 1 catégorie → N produits ; 1 produit → N lignes d'articles.
- Même démarche qu'en S1 : `reception.*` en `text` → contrôles → `nova.categories` / `nova.products` typées et contraintes, ou `rejets.journal`.
- Contraintes posées : PK, `sku UNIQUE`, FK parent → catégorie, `CHECK` contre l'auto-boucle, FK produit → catégorie, puis FK `order_items.product_id → products`. La FK est créée `NOT VALID` puis validée (`VALIDATE CONSTRAINT`), après le contrôle de couverture. Si un produit vendu manquait, la transaction échouerait sans rien modifier.

### Comptages

| Source | Reçus | Intégrés | Rejetés | Bilan |
| --- | ---: | ---: | ---: | --- |
| categories.csv | 10 | 10 | 0 | OK |
| products.csv | 25 | 24 | 1 | OK |

### Note d'anomalies

| # | Anomalie | Preuve | Traitement |
| --- | --- | --- | --- |
| 1 | **Doublon exact de fiche** : `product_id = 3` reçu deux fois (lignes 3 et 25), une seule version de contenu | M1.2 : 25 lignes pour 24 identifiants | 1re occurrence conservée, ligne 25 dans `rejets.journal` (« doublon exact de product_id ») |
| 2 | **Multiplication si l'on joint le brut** : joindre les ventes à `reception.products` duplique les 33 lignes du produit 3 | M1.9 : 833 lignes au lieu de 800, 33 006,25 € au lieu de 32 717,50 € (+288,75 €) | Toujours joindre `nova.products`, dont la PK garantit 1 ligne par produit |
| 3 | **Ventes antérieures à la mise en vente déclarée** : produit 6, `first_listed_on = 2026-09-15`, vendu dès le 2026-09-01 | M1.8 : 6 lignes avant la date, dont 5 sur des commandes `completed` (62,50 €) | Incohérence **démontrée** entre deux sources, signalée et non corrigée : on ne sait pas laquelle des deux dates est fausse. Les ventes sont conservées (CA réel encaissé) |
| — | Couverture | M1.5 : 24 produits vendus = 24 produits au catalogue, 0 vendu hors catalogue, 0 jamais vendu | FK validée sans rejet |
| — | Rejets S1 | M1.6 : les 2 lignes d'articles rejetées en S1 (doublon `order_item_id 7`, commande inconnue 9999) portent les produits 5 et 1, qui sont au catalogue | Leurs rejets venaient de la commande, pas du produit |
| — | Hiérarchie | 2 racines (Maison, Loisirs), 10 catégories atteintes, aucun orphelin, aucun cycle ; les produits sont tous dans des feuilles (4 par feuille) | Voir M5 |

---

## M2 — Classements

### Produits (M2.1)

- **Grain de sortie** : 1 ligne = 1 produit du catalogue, avec `LEFT JOIN` pour garder un produit sans vente (CA 0). Il n'y en a aucun ici.
- **Groupes de comparaison** : le catalogue entier (`rang_global`) et la catégorie feuille (`PARTITION BY category_id`). Un même rayon regroupe des articles comparables en prix et en usage.
- **Ex æquo** : on retient `RANK()`, qui donne le même rang à deux produits égaux puis laisse un trou. Pour une place de podium, c'est la lecture la plus honnête. Un seul ex æquo existe : produits 7 et 18 à 715,00 €, tous deux 15ᵉ (M2.2). Avec `DENSE_RANK` le suivant est 16ᵉ, avec `RANK` il est 17ᵉ. `ROW_NUMBER` les départage arbitrairement : on fixe donc la clé `product_id` pour un résultat stable.

| Rang | Produit | Catégorie | CA |
| ---: | --- | --- | ---: |
| 1 | 23 | Jeux de table | 2 733,75 € |
| 2 | 20 | Randonnée | 2 430,00 € |
| 3 | 17 | Randonnée | 2 126,25 € |
| … | | | |
| 15 | 7 / 18 (ex æquo) | Outillage / Randonnée | 715,00 € |
| 24 | 3 | Rangement | 236,25 € |

### Clients (M2.3)

- **Population** : les 120 clients ayant au moins une commande `completed`. Les 60 autres n'ont pas de performance à classer.
- Le classement montre **beaucoup d'ex æquo** : 3 clients sont 1ers ex æquo (363,75 €), 4 sont 4ᵉ ex æquo. Le jeu est synthétique. Un « top 3 par ville » avec `RANK` peut donc renvoyer 4 clients ou plus. Il faut l'annoncer, plutôt que couper arbitrairement avec `ROW_NUMBER`.

### Effet d'une duplication (M2.4)

Le même classement calculé en joignant le catalogue brut double le CA du produit 3, qui passe de 236,25 € à 472,50 €. Il remonte de la **24ᵉ à la 21ᵉ place**, et les produits 9, 6 et 1 perdent chacun une place, sans aucune vente réelle en plus. Le total classé devient faux. Un doublon dans une table de dimension fausse donc un classement sans produire d'erreur SQL.

---

## M3 — Évolution entre périodes

### Couverture (M3.1)

| Mois | Du | Au | Jours avec commande | Statut |
| --- | --- | --- | ---: | --- |
| 2026-09 | 01/09 | 30/09 | 30 / 30 | complet |
| 2026-10 | 01/10 | 31/10 | 31 / 31 | complet |
| 2026-11 | 01/11 | 19/11 | 19 / 30 | **incomplet** |

Le calendrier est généré avec `generate_series`. Un mois sans vente apparaîtrait à 0 : `LAG` ne comparerait donc jamais un mois à celui d'avant-hier.

### CA mensuel avec `LAG` / `LEAD` (M3.2)

| Mois | Couverture | Commandes | CA | Mois précédent | Mois suivant | Évolution |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| 2026-09 | complet | 120 | 9 717,50 € | — | 10 261,25 € | — |
| 2026-10 | complet | 124 | 10 261,25 € | 9 717,50 € | 6 231,25 € | +5,6 % |
| 2026-11 | incomplet (19/11) | 76 | 6 231,25 € | 10 261,25 € | — | **−39,3 %** |

**La baisse de −39,3 % n'est pas une évolution commerciale : c'est un effet de période incomplète.** À périmètre égal, sur les jours 1 à 19 de chaque mois (M3.3), les trois mois font 6 228,75 €, 6 191,25 € et 6 231,25 € (−0,6 % puis +0,6 %) avec 76 commandes chacun. L'activité est stable. Il en va de même par catégorie (M3.5) : toutes les catégories « chutent » de 32 à 43 % en novembre pour la même raison. Par semaine (M3.4), seules la première (démarrée le 01/09, un mardi) et la dernière (4 jours) sont partielles. Les semaines pleines oscillent entre 2 146 € et 2 438 €.

### Cohérence ventes / catalogue (M3.6)

Le produit 6 a 6 lignes vendues entre le 01/09 et le 14/09, avant sa date de mise en vente (15/09). Ce n'est pas une évolution inhabituelle : une vente ne peut pas précéder la mise en vente, c'est une **incohérence démontrée** entre deux sources. Hypothèses : `first_listed_on` porte la date d'une remise en vente, ou il y a une erreur de saisie. Décision : on garde les ventes et on documente l'anomalie. Il ne faut pas utiliser `first_listed_on` pour calculer une ancienneté produit tant que l'écart n'est pas expliqué.

---

## M4 — Segmentation `NTILE(4)` (A1)

- **Population** : 120 clients avec au moins une commande `completed`. Les 60 sans achat forment un segment à part. Les inclure avec un CA de 0 remplirait le 4ᵉ quartile d'ex æquo à 0.
- **Mesure** : CA `completed`. **Ordre** : CA décroissant, puis `customer_id` comme départage, pour un résultat déterministe.

| Quartile | Clients | CA min | CA max | CA moyen | Part du CA |
| ---: | ---: | ---: | ---: | ---: | ---: |
| Q1 | 30 | 270,00 € | 363,75 € | 309,25 € | 35,4 % |
| Q2 | 30 | 206,25 € | 266,25 € | 237,00 € | 27,1 % |
| Q3 | 30 | 167,50 € | 206,25 € | 189,71 € | 21,7 % |
| Q4 | 30 | 95,00 € | 167,50 € | 137,71 € | 15,8 % |
| sans achat | 60 | 0 | 0 | 0 | 0 |

**Traitement des égalités** (M4.2) : `NTILE` impose des effectifs égaux et coupe des groupes d'ex æquo. Les 10 clients à 206,25 € sont répartis 5 en Q2 et 5 en Q3, et les 4 clients à 167,50 € 1 en Q3 et 3 en Q4. Seul `customer_id` décide, ce qui n'a aucun sens métier. L'alternative M4.3 calcule le quartile à partir du `RANK` : les ex æquo restent ensemble, au prix d'effectifs inégaux (30 / 35 / 28 / 27). Pour une action commerciale par segment, on recommande cette seconde version.

---

## M5 — Hiérarchie des catégories (`WITH RECURSIVE`, A1)

```
Loisirs (2)                     Maison (1)
├── Extérieur (4)               ├── Atelier (3)
│   ├── Jardin (22)             │   ├── Outillage (12)
│   └── Randonnée (31)          │   └── Rangement (11)
└── Jeux de table (32)          └── Cuisine (21)
```

- **Parcours** (M5.1) : ancre = racines (`parent IS NULL`), récursion sur les enfants. La clause `CYCLE category_id SET est_cycle` arrête et signale un cycle, et une borne `profondeur < 20` sert de garde-fou. Résultat : aucun cycle, profondeur maximale 2.
- **Rattachements** (M5.2) : 10 catégories, 10 atteintes depuis une racine, 0 orpheline, 0 atteinte deux fois, 0 produit rattaché à une catégorie intermédiaire.
- **CA par branche** (M5.3) : on construit la table de fermeture (ancêtre, descendant), où chaque catégorie est sa propre descendante. Le CA des feuilles remonte ensuite à tous les ancêtres.

| Branche | Sous-catégories | Produits | CA consolidé | Part |
| --- | ---: | ---: | ---: | ---: |
| **Loisirs** | 4 | 12 | 17 966,25 € | 68,5 % |
| ├ Extérieur | 2 | 8 | 11 820,00 € | 45,1 % |
| │ ├ Randonnée | 0 | 4 | 6 766,25 € | 25,8 % |
| │ └ Jardin | 0 | 4 | 5 053,75 € | 19,3 % |
| └ Jeux de table | 0 | 4 | 6 146,25 € | 23,5 % |
| **Maison** | 4 | 12 | 8 243,75 € | 31,5 % |
| ├ Atelier | 2 | 8 | 4 766,25 € | 18,2 % |
| │ ├ Outillage | 0 | 4 | 3 100,00 € | 11,8 % |
| │ └ Rangement | 0 | 4 | 1 666,25 € | 6,4 % |
| └ Cuisine | 0 | 4 | 3 477,50 € | 13,3 % |

**Double comptage** (M5.4) : la somme des deux racines vaut 26 210,00 €, soit exactement le CA. La somme de toutes les lignes du tableau vaut 69 006,25 €, car chaque vente est comptée une fois par niveau d'ancêtre. On n'additionne donc que des branches disjointes (les racines, ou les feuilles), jamais des niveaux différents.

---

## Limites d'interprétation

- Jeu synthétique et court (11 semaines, du 01/09 au 19/11). Les écarts mensuels de quelques pourcents ne sont pas significatifs, et les nombreux ex æquo clients viennent de prix et de paniers répétitifs.
- Le CA est un CA de lignes d'articles sur les commandes `completed`, pas un encaissement : voir le rapprochement des paiements en S1.
- Le classement et la segmentation clients ne tiennent pas compte de l'ancienneté. Un client arrivé en novembre est désavantagé par la période incomplète.
