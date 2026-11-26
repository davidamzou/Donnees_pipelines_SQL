# S5 · Streaming Hugging Face, PySpark et Hub — synthèse

Séance du 26/11/2026. Tout le travail est dans `novamarket/volumetrie/` (kit du ZIP intégré tel quel, scripts personnels ajoutés à côté). Aucun fichier S1–S4 n'a été modifié, à part un service ajouté dans `compose.yaml`.

| Mission | Script | Preuve |
|---|---|---|
| M1 Fiche source | [hf_datasets/fiche_source.py](hf_datasets/fiche_source.py) | [01_fiche_source.json](resultats/01_fiche_source.json) |
| M2 Streaming borné | [streaming/extraire.py](streaming/extraire.py) | [02_bilan_extraction.json](resultats/02_bilan_extraction.json), [03_interruption.txt](resultats/03_interruption.txt) |
| M3 Contrôle qualité | [streaming/controler.py](streaming/controler.py) | [04_bilan_qualite.json](resultats/04_bilan_qualite.json) |
| M4 Pipeline PySpark | [spark/pipeline.py](spark/pipeline.py) | [05_spark_pipeline.txt](resultats/05_spark_pipeline.txt), [06_spark_secours.txt](resultats/06_spark_secours.txt) |
| M5 Hub | [publication/preparer.py](publication/preparer.py) | [07_dataset_card_v1.md](resultats/07_dataset_card_v1.md), [08_dataset_card_v2.md](resultats/08_dataset_card_v2.md), SHA ci-dessous |

## Relancer

Le poste n'a ni Java 21 ni Python 3.12. J'ai donc ajouté une image (`volumetrie/Dockerfile` : Python 3.12.16, OpenJDK 21.0.13, verrou `requirements.txt` du kit) et un service Compose `volumetrie` (profil `volumetrie`, 2 CPU, 2 Go, `novamarket/` monté sur `/work`). Depuis `novamarket/` :

```bash
export NOVAMARKET_UID=$(id -u) NOVAMARKET_GID=$(id -g)
docker compose --profile volumetrie build volumetrie
docker compose run --rm volumetrie volumetrie/run_s5.sh             # M1 → M4 + publication v1 (≈ 1 min)
docker compose run --rm volumetrie volumetrie/run_s5.sh --secours   # sans réseau (streaming NON validé)
```

Avec un venv local (Java 21 et les variables du livret exportées), la même commande sans Docker : `./volumetrie/run_s5.sh`. L'entrypoint de l'image déclare l'UID du poste dans `/etc/passwd`, sinon Hadoop refuse de démarrer (`Invalid UID, could not determine effective user`).

Chaque exécution Spark écrit dans un dossier neuf `volumetrie/data/sorties/yellow-2024-01-<horodatage>`. Si le dossier existe déjà, le script s'arrête : `Refus : … existe déjà ; choisir un dossier de sortie neuf.`

## M1 · Fiche source

| Élément | Valeur |
|---|---|
| Identifiant | `DinoPonjevic/NYC_TaxiData` (miroir HF des données TLC) |
| Révision | `5941adbf8c0b9930e47002dc3103de3f9291360d` (contrôlée : `revision_conforme = true`) |
| Taille du dépôt | 371 Parquet, 39 350 805 895 octets (≈ 39,35 Go) : fhvhv 20,6 Go, yellow 17,5 Go, green 1,25 Go |
| Partition | `2024/yellow/yellow_tripdata_2024-01.parquet` : 41 899 074 octets, **2 964 624 lignes**, 3 groupes de lignes (1 048 576 au premier) |
| Schéma de la partition | 14 colonnes : `Type`, `Vendor_ID`, 4 horodatages, `Passengers`, `Start_Zone`, `End_Zone`, `Trip_Distance`, `Payment_Type`, `Forward_Stored_Flag`, `Tip_Amount`, `Trip_Duration` |
| Colonnes projetées | `Start_Zone` int32 (LocationID TLC 1–265) · `Trip_Distance` float32 (miles) · `Trip_Duration` int64 (secondes) |
| Anomalies visibles dans les stats Parquet | groupe 0 : distance max 10 879 miles, durée min −697 s, max 217 306 s (≈ 60 h) |
| Licence | `unknown` sur le miroir. Source TLC sous les conditions NYC Open Data. Lecture et analyse en local autorisées, **pas de republication des lignes**. Pas de données passagers selon la TLC |

La fiche ne parcourt aucune ligne : elle combine l'API de métadonnées et le pied de page Parquet, lu par plages HTTP.

**Pourquoi pas de chargement intégral en RAM.** Le dépôt pèse 39 Go compressés, soit environ 2,8 milliards de lignes si l'on extrapole à partir des 42 Mo et 3 M lignes de la partition. Le conteneur dispose de 2 Go et la machine de 8 Go. Même la seule partition, décompressée dans un DataFrame pandas avec ses 14 colonnes, dépasse plusieurs centaines de Mo. Le besoin réel, lui, tient en 3 colonnes et en un échantillon borné.

| Outil | Quand le choisir |
|---|---|
| **pandas** | Le fichier tient largement en mémoire (≲ 1/5 de la RAM) et on travaille sur un seul poste de façon interactive. Il charge tout d'un bloc, avec un seul cœur. |
| **HF Datasets** (`streaming=True`) | Pour parcourir une source distante plus grosse que le disque ou la RAM, ligne par ligne ou par lots courts, avec projection des colonnes et une révision épinglée. Bon outil pour échantillonner ou extraire. Peu adapté aux jointures et agrégations lourdes. |
| **Spark** | Pour des transformations relationnelles (jointure, agrégation, échange) sur des volumes qui dépassent un seul processus. Exécution paresseuse, plan optimisé, partitions traitées en parallèle, débordement sur disque. Le coût fixe (JVM, ~5 s) ne se justifie pas pour un petit fichier. |

## M2 · Streaming borné

`extraire.py` réutilise `acces.ouvrir()` (révision épinglée, 3 colonnes, `pre_buffer=False`, lots de 128). Chaque enregistrement est lu, compté **avant** tout filtrage, contrôlé, puis écrit ou rejeté. Rien n'est matérialisé en mémoire.

- Règle de validité structurelle : les 3 champs sont présents et non nuls, zone et durée sont des entiers, la distance est un nombre fini. La plausibilité est laissée à M3.
- Traçabilité : chaque ligne garde `ligne_source`, son rang dans le flux. Le bilan consigne la révision, la partition, la limite et le SHA-256 du JSONL.
- Fermeture : `flux.close()` dans un `finally`. L'écriture passe par un fichier `.partiel` renommé seulement en fin de parcours.

Résultat (`--limite 200000`) : **200 000 parcourues = 200 000 retenues + 0 rejetée**, en 9,7 s (≈ 20 700 lignes/s). Le JSONL fait 18,8 Mo. On a donc lu 6,7 % des lignes de la partition et ≈ 0,05 % du dépôt. Aucun rejet structurel n'est un résultat attendu : le Parquet est typé et ses statistiques indiquent 0 nul.

Test d'interruption ([03_interruption.txt](resultats/03_interruption.txt)) : un SIGINT après 5 s laisse le statut `interrompu`, 57 196 lignes parcourues, `sortie: null`, et seulement un `.jsonl.partiel`. Aucun fichier incomplet ne peut passer pour une extraction valide.

## M3 · Contrôle qualité → entrée Spark

`controler.py` lit le fichier ligne à ligne. Les règles sont appliquées dans l'ordre, et le premier échec donne le motif du rejet :

| Règle | Seuil | Rejets |
|---|---|---|
| Q1 type / Q2 manquant | entiers, nombre fini, non nul | 0 |
| Q3 `distance_non_positive` | distance > 0 | 3 414 |
| Q4 `distance_aberrante` | ≤ 100 miles | 5 |
| Q5 `duree_non_positive` | durée > 0 | 1 |
| Q6 `duree_aberrante` | ≤ 6 h (21 600 s) | 180 |
| Q7 `vitesse_aberrante` | ≤ 80 mph | 74 |

Bilan : **200 000 lues → 196 326 conformes, 3 674 rejetées (1,84 %)**. La distance est arrondie au centième pour supprimer l'artefact float32 (1.7200000286 → 1.72).

| | Distance (mi) min / max / moy. | Durée (s) min / max / moy. | Zones |
|---|---|---|---|
| Avant | 0,00 / 10 879,28 / 4,094 | −364 / 112 734 / 1 008 | 235 |
| Après | 0,01 / 97,12 / 4,097 | 1 / 17 029 / 947 | 234 |

Les zones ne sont pas filtrées ici : M4 doit pouvoir détecter les non-appariements. Les sorties sont `data/spark/trajets_controles.jsonl` (entrée Spark) et `data/spark/trajets_rejetes.jsonl` (chaque rejet avec son motif et sa `ligne_source`). Le bilan chaîne les SHA-256 : la sortie M2 est l'entrée M3 (`fb555db8…`).

Limite connue : une course de 0,01 mile en 1 s passe toutes les règles. Un seuil de durée minimale serait discutable sans connaître le protocole du compteur.

## M4 · Pipeline PySpark

`pipeline.py` (local[2], 4 partitions de shuffle, AQE actif) effectue les étapes suivantes :

1. **Schémas.** Il affiche le schéma inféré puis lit avec un `StructType` imposé, en mode `PERMISSIVE` + `_corrupt_record` (0 ligne corrompue). Les zones sont lues tout en chaîne puis converties en `int`.
2. **Typage et manquants.** Colonnes renommées `zone_depart` int, `distance_miles` double, `duree_s` int. 0 manquant.
3. **Filtre et variable calculée.** Les mêmes règles qu'en M3 sont rejouées par sécurité : 196 326 → 196 326. Sur le secours, 6 → 5 (distance −2,0 écartée). Il calcule ensuite `vitesse_mph = distance / (durée / 3600)`.
4. **Clé de zones.** 265 lignes, 265 `LocationID` distincts, 0 nul : la jointure ne peut pas multiplier. En revanche, les **noms** ne sont pas uniques (Corona ×2, Governor's Island ×3) : une jointure sur `Zone` aurait dupliqué des trajets.
5. **Non-appariements.** L'anti-jointure ne trouve aucune zone absente de la table (sur le secours : 1, la zone 999). 786 trajets sont appariés aux zones « non localisées » 264 *Unknown* (730) et 265 *Outside of NYC* (56). On les garde, sous leur propre libellé.
6. **Jointure gauche.** 196 326 avant, 196 326 après, `ligne_source` unique. Les assertions bloquent toute multiplication.
7. **Agrégats.** Par arrondissement (`par_arrondissement`) et par zone de départ (`par_zone`, 234 zones).
8. **Export Parquet** (`errorifexists`), relecture : Σ `nb_trajets` = 196 326 dans les deux agrégats.

| Arrondissement | Trajets | Part | Dist. moy. | Dist. médiane | Durée moy. | Vitesse pondérée |
|---|---:|---:|---:|---:|---:|---:|
| Manhattan | 167 166 | 85,15 % | 2,63 mi | 1,64 mi | 13,1 min | 12,1 mph |
| Queens | 26 175 | 13,33 % | 13,29 mi | 12,20 mi | 31,8 min | 25,1 mph |
| Brooklyn | 1 783 | 0,91 % | 6,15 mi | 4,49 mi | 30,7 min | 12,0 mph |
| Unknown (264) | 730 | 0,37 % | 4,22 mi | 1,96 mi | 15,6 min | 16,3 mph |
| Bronx | 403 | 0,21 % | 8,27 mi | 7,43 mi | 39,2 min | 12,7 mph |
| N/A (265) | 56 | 0,03 % | 4,60 mi | 0,50 mi | 14,9 min | 18,6 mph |
| EWR | 10 | 0,01 % | 6,21 mi | 0,06 mi | 13,6 min | 27,3 mph |
| Staten Island | 3 | 0,00 % | 6,20 mi | 0,60 mi | 14,0 min | 26,6 mph |

Top zones : JFK Airport (15 563, 16,1 mi en moyenne), Midtown Center, Upper East Side South, Penn Station, LaGuardia.

**Justification des agrégations.**
- La vitesse est **pondérée** (Σ distance / Σ heures) et non une moyenne des vitesses par trajet : celle-ci surpondérerait les courses très courtes, dont la vitesse est la plus bruitée.
- La **médiane** (`percentile_approx`, précision 10 000) accompagne la moyenne parce que les distributions sont asymétriques. Pour EWR, la moyenne vaut 6,2 mi et la médiane 0,06 mi : quelques longues courses masquent des prises en charge quasi immobiles.
- La part en % donne la représentativité : en dessous de quelques dizaines de trajets (EWR, Staten Island), les indicateurs ne sont pas interprétables.

**Plan d'exécution commenté** (`explain(mode="formatted")`, [05_spark_pipeline.txt](resultats/05_spark_pipeline.txt)) :
- `Scan json` avec `ReadSchema: struct<ligne_source:bigint,Start_Zone:bigint,…>` : le schéma imposé est bien celui utilisé, sans inférence.
- `Filter` puis `Project [codegen id : 1]` : filtres qualité et calcul de `vitesse_mph` fusionnés en un seul étage de génération de code. Le prédicat de vitesse est répété dans le filtre, car l'optimiseur a remplacé l'alias par son expression.
- `InMemoryRelation` / `TableCacheQueryStage (rowCount=1.96E+5, 6.0 MiB)` : effet des `cache()`, qui évitent de relire le JSONL à chaque `count()` de contrôle.
- `BroadcastExchange` + `BroadcastHashJoin LeftOuter BuildRight` : la table de zones (265 lignes) est diffusée à chaque tâche. **Les trajets ne sont pas redistribués**, d'où 2 partitions avant et après la jointure.
- `ObjectHashAggregate` partiel → `Exchange hashpartitioning(arrondissement, 4)` → `ObjectHashAggregate` final : agrégation en deux phases, avec un seul échange réseau. `Object…` plutôt que `HashAggregate` à cause du tampon de `percentile_approx`.
- `Exchange rangepartitioning(nb_trajets DESC)` + `Sort` : coût du `orderBy`.
- `AdaptiveSparkPlan` : à l'exécution, AQE regroupe les 4 partitions de shuffle en **1**, car 8 groupes ne justifient pas plus. `coalesce(1)` avant l'écriture produit un seul fichier Parquet par agrégat, ce qui est raisonnable pour quelques Ko.

## M5 · Hub : deux révisions documentées

**Données publiées.** Seulement le jeu **synthétique** du kit (`secours/trajets_fictifs.jsonl`), enrichi par la table officielle des zones TLC. Aucune ligne du miroir (licence `unknown`).

`preparer.py` écrit `publication/` avec **exactement** `README.md` (Dataset Card construite sur le modèle) et `trajets_synthetiques.parquet`. Si un autre fichier est présent, le script refuse de continuer, ce qui évite de publier par erreur un token, un cache ou un brouillon.

| Version | Contenu | Card |
|---|---|---|
| v1 | 5 trajets conformes (la distance −2,0 est écartée), joints aux zones. Zone 999 gardée en « Zone inconnue » | [07_dataset_card_v1.md](resultats/07_dataset_card_v1.md) |
| v2 | Zone 999 retirée (hors référentiel TLC, elle faussait la répartition : 1 trajet sur 5), colonne `vitesse_mph` ajoutée. 5 → 4 lignes | [08_dataset_card_v2.md](resultats/08_dataset_card_v2.md) |

Le même nom de fichier est conservé dans les deux versions pour comparer le Parquet d'une révision à l'autre.

**Procédure.** Le token est saisi **uniquement** dans l'invite de `hf auth login`. Dans un shell du conteneur, il disparaît avec le conteneur (`--rm`), donc il n'est jamais stocké sur le poste ni dans le dépôt.

```bash
docker compose run --rm volumetrie bash        # puis, dans le conteneur (/work = novamarket/) :
hf auth login                                  # token "write" de SON compte, saisi dans l'invite
hf auth whoami
repo="VOTRE_COMPTE/novamarket-s5-exercice"
python volumetrie/publication/preparer.py --version 1 && ls -la publication && cat publication/README.md
hf repo create "$repo" --repo-type dataset --private
hf upload "$repo" ./publication . --repo-type dataset --commit-message "v1 : premier jeu vérifié"
python volumetrie/publication/preparer.py --version 2 && ls -la publication
hf upload "$repo" ./publication . --repo-type dataset --commit-message "v2 : changement documenté"
# relever les deux SHA (URL de commit affichée par hf upload, ou historique du dépôt) :
python -c "from huggingface_hub import HfApi; [print(c.commit_id, c.title) for c in HfApi().list_repo_commits('$repo', repo_type='dataset')]"
sha_v1=…; sha_v2=…
hf download "$repo" README.md --repo-type dataset --revision "$sha_v1" --local-dir /tmp/v1
hf download "$repo" README.md --repo-type dataset --revision "$sha_v2" --local-dir /tmp/v2
hf download "$repo" trajets_synthetiques.parquet --repo-type dataset --revision "$sha_v1" --local-dir /tmp/v1
hf download "$repo" trajets_synthetiques.parquet --repo-type dataset --revision "$sha_v2" --local-dir /tmp/v2
diff /tmp/v1/README.md /tmp/v2/README.md
hf auth logout
```

En cas d'erreur : un 401 signale un problème d'authentification (token absent ou révoqué), un 403 un problème de permissions ou d'espace de noms (token en lecture seule, organisation non autorisée).

| Élément | Valeur |
|---|---|
| Dépôt privé | `À COMPLÉTER : https://huggingface.co/datasets/<compte>/novamarket-s5-exercice` (accès formateur à accorder) |
| SHA v1 | `À COMPLÉTER` |
| SHA v2 | `À COMPLÉTER` |
| Vérification | `À COMPLÉTER : diff README v1/v2 et effectifs Parquet 5 / 4` |

**État au 26/11.** Les deux versions sont préparées et vérifiées en local (cards ci-dessus, Parquet 5 puis 4 lignes). **La publication distante n'est pas encore faite** : elle exige l'authentification personnelle sur le Hub, qui ne peut pas être automatisée. Il faut la régulariser avec les commandes ci-dessus. S6 peut démarrer en parallèle.

## Reproductibilité et limites

- Versionné : scripts, bilans JSON, journaux Spark, cards. Non versionné (`.gitignore`) : `volumetrie/data/` (extraction de 18,8 Mo issue d'une source sous licence `unknown`, sorties Parquet) et `publication/` (régénérée par `preparer.py`). Aucun token, aucun fichier d'authentification.
- Échantillon : ce sont les 200 000 **premières** lignes du flux, pas un tirage aléatoire. Leur ordre suit celui du fichier, donc probablement le début du mois. Les parts par arrondissement ne valent que pour cet échantillon. Un tirage représentatif demanderait de parcourir les 3 groupes de lignes.
- Le réseau reste le point fragile du streaming. Le mode `--secours` valide Spark, la card et la préparation Hub, mais **pas** le streaming distant.
- Les seuils qualité (100 mi, 6 h, 80 mph) sont des choix métier documentés. Ils ne viennent pas de la TLC.
