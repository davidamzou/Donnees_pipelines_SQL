# Données & pipelines SQL — NovaMarket

Travaux pratiques SQL (S1 → S6) sur PostgreSQL 17, avec dbt (S4–S5) et Metabase (S6), le tout lancé via Docker Compose.

## Structure

```
.
├── novamarket/            # Kit technique : lancer les commandes depuis ce dossier
│   ├── compose.yaml       # PostgreSQL, dbt (profil transfo), Metabase (profil bi)
│   ├── s1/
│   │   ├── DEMARRAGE.md   # Guide de démarrage et dépannage
│   │   ├── SOURCES.md     # Dictionnaire des fichiers sources
│   │   ├── SOLUTION_S1.md # Solution S1 (schéma, imports, indicateurs, anomalies)
│   │   ├── donnees/       # Données brutes (montées en lecture seule sur /s1)
│   │   ├── exemple/       # Exemple indépendant (ateliers culturels)
│   │   └── sql/           # Scripts S1 + run_all.sh
│   ├── s2/                # Catalogue + SQL avancé (fenêtres, CTE, récursif)
│   │   ├── SOLUTION_S2.md
│   │   ├── donnees/       # categories.csv, products.csv (bruts, non modifiés)
│   │   ├── sql/           # 10_…15_*.sql + run_s2.sh
│   │   └── resultats/     # sorties psql de chaque script
│   ├── s3/                # Benchmark 10 M lignes, index, plans
│   │   ├── SOLUTION_S3.md
│   │   ├── generer.sql    # générateur fourni (schéma benchmark)
│   │   ├── sql/           # 20_…23_*.sql, requetes/, run_s3.sh, synthese.py
│   │   └── resultats/     # plans EXPLAIN complets, mesures.csv, synthese.md
│   ├── ingestion/         # S3 · collecteur asynchrone de l'API fournisseur
│   │   ├── CONTRAT.md     # Contrat HTTP et règles de données (M1)
│   │   ├── SOLUTION_S3_INGESTION.md
│   │   ├── api/           # Dockerfile à 2 cibles : API « fournisseur » + client « collecteur »
│   │   ├── src/           # collecteur.py, validation.py, journalisation.py
│   │   ├── tests/         # disponibilite.py + tests unitaires et d'intégration
│   │   └── data/          # raw/ valid/ rejected/ logs/ bilans/ (runs de référence)
│   ├── transformation/    # S4 · chargeur PostgreSQL + projet dbt unique
│   │   ├── SOLUTION_S4.md
│   │   ├── chargement_postgres.py, sql/, exemple_lots/, run_s4.sh
│   │   ├── dbt/           # sources, staging, intermediate, marts, tests (monté sur /projet)
│   │   └── resultats/     # preuves : chargement, rejeu, atomicité, dbt build, volumes
│   ├── s4/                # support formateur : image dbt + exemple des cuves (travail/ ignoré)
│   ├── volumetrie/        # S5 · streaming HF, PySpark, publication Hub
│   │   ├── SOLUTION_S5.md
│   │   ├── hf_datasets/   # source.json épinglé, acces.py, fiche_source.py (M1)
│   │   ├── streaming/     # extraire.py (M2), controler.py (M3)
│   │   ├── spark/         # pipeline.py (M4)
│   │   ├── publication/   # preparer.py (M5 : Dataset Card + Parquet synthétique)
│   │   ├── resultats/     # preuves : fiche, bilans, journaux Spark, cards v1/v2
│   │   └── Dockerfile, run_s5.sh   # Python 3.12 + Java 21 ; data/ ignoré
│   ├── requirements-v3.txt # dépendances Python 3.12 (aiohttp, psycopg)
│   ├── REFERENCE_SQL.md   # Référence cumulative (version S2)
│   └── SAUVEGARDE_SQL.md  # Sauvegarde / restauration
├── ressources/
│   └── REFERENCE_SQL.md   # Référence SQL cumulative S1–S6
└── livrets/               # Énoncés des TP (.docx)
```

## Démarrer

### Dans GitHub Codespaces (sans rien installer)

Bouton **Code → Codespaces → Create codespace**, puis dans le terminal :

```bash
cd novamarket
docker compose up -d --wait postgres
docker compose exec postgres psql -X -U atelier -d novamarket
```

Pense à arrêter le codespace en fin de séance pour préserver le quota gratuit.

### En local

Prérequis : Docker Desktop (ou OrbStack / Colima). Mêmes commandes, depuis `novamarket/`.
Voir [novamarket/s1/DEMARRAGE.md](novamarket/s1/DEMARRAGE.md) pour le détail.

## Rejouer tout le dossier S1 → S3 (évaluation collective n°1)

Depuis `novamarket/`, dans cet ordre (chaque étape dépend de la précédente) :

```bash
docker compose up -d --wait postgres
./s1/sql/run_all.sh                 # S1 : schémas reception / rejets / nova, imports, indicateurs
./s2/sql/run_s2.sh                  # S2 : catalogue + analyses avancées -> s2/resultats/
docker compose exec -T postgres psql -X -v ON_ERROR_STOP=1 -U atelier -d novamarket < s3/generer.sql
./s3/sql/run_s3.sh                  # S3 : benchmark avant/après index -> s3/resultats/
```

- `run_all.sh` recrée les schémas S1 (`DROP SCHEMA … CASCADE`) : relancer ensuite `run_s2.sh`.
- `generer.sql` ne s'exécute qu'une fois (le 2e passage échoue sur le schéma existant et annule) ; `run_s3.sh` est rejouable et repart toujours d'une table sans index.
- Durées indicatives sur un portable (2 CPU / 2 Go pour le conteneur) : S1 + S2 < 10 s, génération ≈ 10 s, benchmark ≈ 1 min.

Livrables : [SOLUTION_S1](novamarket/s1/SOLUTION_S1.md) · [SOLUTION_S2](novamarket/s2/SOLUTION_S2.md) · [SOLUTION_S3](novamarket/s3/SOLUTION_S3.md)

## S3 · Ingestion asynchrone (API fournisseur)

Depuis `novamarket/`, avec Python 3.12. L'API tourne sans PostgreSQL :

```bash
python3.12 -m venv .venv && source .venv/bin/activate
python -m pip install -r requirements-v3.txt
docker compose up -d --build --wait fournisseur
python ingestion/src/collecteur.py --scenario atelier
python -m unittest discover -s ingestion/tests -v
```

Les commandes `docker compose` marchent aussi depuis la racine du dépôt : le [compose.yaml](compose.yaml) racine inclut `novamarket/compose.yaml`, avec le même nom de projet, donc les mêmes conteneurs et le même volume.

Sans Python 3.12 en local, le service `collecteur` (même Dockerfile que l'API, cible `collecteur`) embarque les dépendances :

```bash
docker compose --profile ingestion build
docker compose run --rm collecteur --scenario atelier
docker compose run --rm --entrypoint python collecteur -m unittest discover -s ingestion/tests -v
```

Résultat attendu sur `atelier` : 24 offres examinées, 20 valides publiées dans `ingestion/data/valid/offres.jsonl` (entrée de S4), 4 rejets motivés. Détails : [CONTRAT](novamarket/ingestion/CONTRAT.md) · [SOLUTION_S3_INGESTION](novamarket/ingestion/SOLUTION_S3_INGESTION.md)

## S4 · Chargement PostgreSQL et dbt

Depuis `novamarket/`, après S1/S2 et S3. Le mot de passe local se saisit dans la session, jamais dans un fichier :

```bash
read -rs PGPASSWORD; echo; export PGPASSWORD DBT_ENV_SECRET_PASSWORD="$PGPASSWORD"
./transformation/run_s4.sh --reinitialiser
```

Charge `ingestion/data/valid/offres.jsonl` dans `fournisseur.offres` (grain : offre × jour), rejoue le lot (20 réutilisées, 0 doublon), prouve l'atomicité, puis exécute `dbt compile / run / build` (PASS=41). Détails et preuves : [SOLUTION_S4](novamarket/transformation/SOLUTION_S4.md)

## S5 · Streaming Hugging Face, PySpark et Hub

Depuis `novamarket/`. Sans Java 21 ni Python 3.12 en local, le service `volumetrie` les embarque :

```bash
export NOVAMARKET_UID=$(id -u) NOVAMARKET_GID=$(id -g)
docker compose --profile volumetrie build volumetrie
docker compose run --rm volumetrie volumetrie/run_s5.sh
```

Lit en streaming 200 000 lignes de la partition Yellow 2024-01 (révision épinglée, sans rapatrier les 39,35 Go du dépôt), applique les contrôles qualité (196 326 conformes, 3 674 rejets motivés), puis exécute le pipeline Spark : jointure aux zones TLC sans multiplication, agrégats, Parquet relu. Prépare ensuite `publication/` (jeu synthétique uniquement). La publication des deux révisions sur le Hub demande `hf auth login` avec son propre token. Détails et preuves : [SOLUTION_S5](novamarket/volumetrie/SOLUTION_S5.md)
