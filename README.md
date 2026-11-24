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
