# NovaMarket S4 — Solution : chargement PostgreSQL et dbt

Les offres validées en S3 sont chargées dans PostgreSQL de façon transactionnelle et rejouable (M1). Elles sont ensuite transformées par dbt en staging, intermediate et un premier mart (M2 à M4), avec 33 tests de volumes et de relations (M5). Toutes les preuves sont dans [`resultats/`](resultats/).

## Reproduire

Depuis `novamarket/`, PostgreSQL chargé par S1/S2. Le mot de passe local se saisit dans la session, jamais dans un fichier :

```bash
read -rs PGPASSWORD; echo; export PGPASSWORD DBT_ENV_SECRET_PASSWORD="$PGPASSWORD"
```

```bash
./transformation/run_s4.sh --reinitialiser
```

Le script utilise les services Compose `chargeur` et `dbt`, et n'a besoin d'aucun Python local. Il :
- recrée les schémas `fournisseur` et `dbt_dev_*` (option `--reinitialiser`) ;
- charge puis rejoue le lot S3 ;
- prouve l'atomicité, puis lance les essais ;
- exécute `dbt compile`, `run` et `build`, puis écrit `resultats/01…07`.

Commandes à l'unité :

```bash
docker compose --profile transfo run --rm -e PGPASSWORD chargeur
```

```bash
docker compose --profile transfo run --rm -e PGPASSWORD chargeur --fichier transformation/secours/offres.jsonl --essai
```

```bash
docker compose --profile transfo run --rm --no-deps --user "$(id -u):$(id -g)" -w /projet -e DBT_ENV_SECRET_PASSWORD -e DBT_DATABASE dbt dbt build --profiles-dir /work/profil
```

Avec le venv S3 : `export NOVAMARKET_DSN='host=127.0.0.1 port=15432 dbname=novamarket user=atelier'`, puis `python transformation/chargement_postgres.py` (mot de passe par `PGPASSFILE` ou `PGPASSWORD`).

| Fichier | Rôle |
| --- | --- |
| [`chargement_postgres.py`](chargement_postgres.py) | M1 : lecture, contrôles, transaction, UPSERT, bilan |
| [`sql/schema_fournisseur.sql`](sql/schema_fournisseur.sql) | M1 : schéma `fournisseur`, clés et contraintes (rejouable) |
| [`exemple_lots/`](exemple_lots/) | lots de démonstration : autre jour, correction de prix, lot défectueux |
| [`dbt/`](dbt/) | M2–M5 : le projet dbt unique du groupe (monté sur `/projet`) |
| [`sql/verifications_s4.sql`](sql/verifications_s4.sql) | M5 : volumes par couche, totaux, contenu du mart |
| [`run_s4.sh`](run_s4.sh) | reproduction complète et preuves |
| [`../s4/`](../s4/) | support du formateur : image dbt (dbt-core 1.11.17, dbt-postgres 1.10.2, Git) et exemple indépendant des cuves ; `s4/travail/` (profil local) est ignoré par Git |

## M1 — Chargement

### Grain, schéma et clé

- **Grain** : une offre fournisseur **observée un jour donné**. L'API livre des observations, et une même offre (`O001`) peut revenir chaque jour avec un autre prix ou un autre stock.
- **Clé** : `(offer_id, observed_on)`. Une nouvelle date crée une ligne. Le même jour rejoué retombe sur la même ligne.
- **Schéma `fournisseur`**, séparé de `nova` (données de l'entreprise) et des schémas dbt :

| Table | Contenu |
| --- | --- |
| `fournisseur.offres` | les observations ; clé étrangère vers `nova.products` et vers `fournisseurs` ; `CHECK` prix ≥ 0, unités ≥ 0, devise `EUR` ; lots d'insertion et de dernière mise à jour |
| `fournisseur.fournisseurs` | référentiel F01, F02, F03 |
| `fournisseur.lots` | une ligne par exécution : fichier, SHA-256, run S3 (lu dans le manifeste S3), statut, compteurs, erreur. Deux `CHECK` imposent lues = acceptées + rejetées et acceptées = insérées + mises à jour + réutilisées |
| `fournisseur.lot_lignes` | le sort de chaque ligne de chaque lot : `inseree`, `mise_a_jour`, `reutilisee` ou `rejetee` avec ses motifs et la ligne brute |

### Contrôles avant écriture

Les contrôles du collecteur S3 sont rejoués, car le fichier peut venir d'ailleurs (secours, autre groupe) :
- JSON lisible ;
- champs présents et non nuls ;
- entiers stricts pour le prix et les unités, sans négatif ;
- devise `EUR` ;
- date ISO qui existe et n'est pas dans le futur ;
- produit présent dans **`nova.products`** (la base, et non plus le CSV) ;
- fournisseur connu ;
- doublon de clé dans le même lot.

La date texte est convertie en `date`.

### Transaction et rejeu

Le lot entier tient dans **une seule transaction**. Un verrou consultatif empêche deux chargements simultanés.

L'écriture est un `INSERT … ON CONFLICT (offer_id, observed_on) DO UPDATE … WHERE (colonnes) IS DISTINCT FROM (nouvelles valeurs) RETURNING (xmax = 0)`. On en déduit trois cas :
- **insérée** : `xmax = 0` ;
- **mise à jour** : le contenu a changé ;
- **réutilisée** : aucune ligne n'est retournée, l'observation était déjà là à l'identique et rien n'est réécrit.

En cas d'erreur, tout est annulé. Le lot est ensuite tracé `annule` dans une transaction séparée, avec le message d'erreur et sans aucune offre.

### Preuves

| Exécution | Lues | Insérées | Mises à jour | Réutilisées | Rejetées | Offres en base |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Lot 1 : lot S3 publié (run `atelier-20261124-124308`) | 20 | **20** | 0 | 0 | 0 | 20 |
| Lot 2 : **rejeu du même fichier** | 20 | 0 | 0 | **20** | 0 | 20 |
| Lot 4 : `jour_precedent`, **panne après 1 insertion** | — | annulé | | | | **20** (0 ligne du 23/11) |
| Essai : `jour_precedent` (2 offres du 23/11 + 1 identique) | 3 | 2 | 0 | 1 | 0 | 20 (annulé) |
| Essai : `correction_prix` (O001 du 24/11 à 6,00 €) | 1 | 0 | 1 | 0 | 0 | 20 (annulé) |
| Essai : `defectueux` | 8 | 0 | 0 | 1 | **7** | 20 (annulé) |

Fichiers : [`01_chargement_et_rejeu.txt`](resultats/01_chargement_et_rejeu.txt), [`02_atomicite.txt`](resultats/02_atomicite.txt), [`03_essais.txt`](resultats/03_essais.txt), [`04_lots.txt`](resultats/04_lots.txt).

- **Idempotence** : le rejeu ne crée aucune ligne et n'en modifie aucune.
- **Plusieurs dates par offre** : l'essai `jour_precedent` insère `O001` et `O002` au 23/11 à côté de leurs observations du 24/11.
- **Atomicité** : la panne survient après une insertion réelle, et la base reste à 20 lignes sans observation du 23/11.
- **Lot défectueux** : les 7 rejets sont tous motivés (`json_invalide`, `produit_hors_catalogue`, `fournisseur_inconnu`, `devise_invalide`, `type_invalide:price_cents`, `valeur_negative:available_units`, `date_future`, `date_inexistante`, `doublon_dans_lot`). Une même ligne peut cumuler plusieurs motifs.
- **Numéros de lot** : il manque les lots 3, 5, 6 et 7. Une identité PostgreSQL consomme sa valeur même quand la transaction est annulée (panne puis essais). C'est voulu : le numéro n'est jamais réutilisé.
- **Fichier de secours** : `secours/offres.jsonl` contient les mêmes 20 offres que notre lot S3 (même contenu, ordre des clés JSON différent). Son chargement donne 20 réutilisées.

## M2 — Projet et sources dbt

Projet unique `transformation/dbt/` (`dbt_project.yml` du kit, complété des matérialisations par couche). Profil `novamarket_dbt` dans `s4/travail/profil/profiles.yml`, copie de `profiles.exemple.yml`, avec le mot de passe lu dans `DBT_ENV_SECRET_PASSWORD`. Ce dossier est ignoré par Git, et `run_s4.sh` le recrée s'il manque. Les sources sont déclarées dans [`models/staging/_sources.yml`](dbt/models/staging/_sources.yml) : `fournisseur.{offres, fournisseurs, lots}` et `nova.{products, categories, orders, order_items}`. `dbt debug` : *All checks passed*.

## M3 — Staging

| Modèle (vue) | Grain | Harmonisation |
| --- | --- | --- |
| `stg_fournisseur__offres` | offre × jour, **inchangé** | `price_eur` dérivé, colonnes de lot renommées |
| `stg_fournisseur__fournisseurs` | fournisseur | — |
| `stg_nova__products` / `stg_nova__categories` | produit / catégorie | — |
| `stg_nova__order_lines` | ligne de commande | statut et date de la commande ajoutés (jointure n-1, volume de `order_items` conservé) |

Aucun filtre en staging : le périmètre métier (`completed`) est appliqué en intermediate.

## M4 — Intermediate et premier mart

| Modèle | Matérialisation | Grain | Rôle |
| --- | --- | --- | --- |
| `int_offres__enrichies` | vue | offre × jour | libellés produit, catégorie, fournisseur ; trois jointures n-1 sur des clés uniques |
| `int_offres__derniere_observation` | **éphémère** | offre | dernière observation de chaque offre (`row_number`) ; injectée comme CTE dans le mart, aucune relation créée |
| `int_ventes__par_produit` | vue | produit vendu | périmètre S2 : commandes `completed`, quantité × prix de transaction |
| **`mart_offres_par_produit`** | **table** | **produit du catalogue (24)** | offres actives, nombre de fournisseurs, meilleur prix et fournisseur, stock annoncé, ventes, écart prix de vente − meilleur prix, statut de couverture |

**Choix des matérialisations.**
- **Vues en amont** : toujours à jour, sans stockage, et faciles à interroger pendant le TP.
- **Éphémère** pour une étape qui ne sert qu'au mart.
- **Table pour le mart** : il est lu par la BI en S6, et une table évite de recalculer toute la chaîne à chaque lecture. En contrepartie, il faut relancer `dbt run` après chaque chargement.

**Grain et jointures du mart.** Le catalogue est la table de départ, pour que les produits sans offre restent visibles. Offres et ventes sont **agrégées par produit avant** les jointures externes. Chaque produit reçoit donc 0 ou 1 ligne de chaque côté, sans multiplication possible.

Lecture du mart ([`07_volumes_et_mart.txt`](resultats/07_volumes_et_mart.txt)) :
- **20 produits** `offre_et_ventes` et **4 produits `vendu_sans_offre`** : 5, 10, 17 et 24. Ce sont exactement les offres perdues en S3 :
  - O005 : `supplier_id` manquant ;
  - O010 : prix `"inconnu"` ;
  - O017 : produit 9999 ;
  - O024 : remplacée par le doublon de O001.
- **Écart prix de vente − meilleur prix = 0** pour les 20 produits couverts. Le simulateur calcule ses prix avec la même formule que les prix de vente S1 (500 + 125 × id). Ce n'est donc pas une erreur de jointure, et cela confirme que le meilleur prix est rattaché au bon produit. Avec de vraies offres, cette colonne donnerait la marge brute unitaire.

## M5 — Vérification de la chaîne

`dbt compile`, `dbt run` (8 modèles) et `dbt build` : **PASS=41, 0 erreur** (8 modèles + 33 tests), dans [`05_dbt.txt`](resultats/05_dbt.txt).

| Couche | Lignes | Grain |
| --- | ---: | --- |
| source `fournisseur.offres` | 20 | offre × jour |
| `stg_fournisseur__offres` | 20 | offre × jour |
| `int_offres__enrichies` | 20 | offre × jour |
| offres distinctes | 20 | offre |
| `mart_offres_par_produit` | 24 | produit |

L'écart 20 → 24 est attendu : le grain change (produit). Somme des offres du mart = 20 = offres distinctes. CA du mart = **2 621 000 centimes = 26 210,00 €**, le CA S2 de référence.

Tests posés :
- **génériques** (`_staging.yml`, `_intermediate.yml`, `_marts.yml`) : `unique` et `not_null` sur les clés ; `relationships` offre → produit, offre → fournisseur, produit → catégorie, mart → produit et fournisseur ; `accepted_values` sur la devise, le statut de commande et le statut de couverture ;
- **singuliers** (`dbt/tests/`) :
  - unicité du grain `(offer_id, observed_on)` ;
  - volumes égaux de la source à l'intermediate ;
  - totaux du mart égaux aux totaux amont (lignes, offres, quantités, CA) ;
  - CA de référence S2 ;
  - valeurs plausibles.

Le SQL compilé du mart est dans [`06_mart_offres_par_produit.compile.sql`](resultats/06_mart_offres_par_produit.compile.sql). On y voit `source()` et `ref()` résolus en noms complets (`"novamarket"."dbt_dev_intermediate"…`), et le modèle éphémère injecté en CTE `__dbt__cte__int_offres__derniere_observation`.

## Limites

- **`s4/` reçu à part** (absent des ZIP S4) : intégré tel quel. La chaîne a été rejouée sur son image (dbt-core 1.11.17), avec le même résultat, PASS=41. Son README cite `s4/preparer_reception.sql` (variantes d'anomalies en réception), qui n'est pas dans le dossier reçu.
- **Ajouts au compose** : le montage `./transformation/dbt:/projet` du service `dbt` (présent dans le compose distribué en S3) et un service `chargeur` (même image Python 3.12 que le collecteur S3), pour lancer le chargeur sans Python local.
- **`run_all.sh` de S1** supprime `nova` en cascade, ce qui retire la clé étrangère `offres → products` et les vues dbt qui lisent `nova`. Le chargeur recrée la clé au lancement suivant, et `dbt run` recrée les vues.
- **Une seule date d'observation dans les données** (24/11) : la logique « dernière observation » n'est démontrée que par l'essai annulé `jour_precedent`.
- **Préparation S5** (Java, PySpark, compte Hugging Face) : le guide `volumetrie/` cité dans le kit n'a pas été fourni. À faire dès sa réception, sans jamais versionner de token.
