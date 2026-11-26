#!/usr/bin/env bash
# S5 · rejoue M1 → M4 et prépare la publication v1 (M5, partie locale).
# À lancer depuis novamarket/, dans le venv S5 (Java 21 + variables exportées) :
#     ./volumetrie/run_s5.sh [--limite N] [--secours]
# ou sans Java/Python 3.12 sur le poste :
#     docker compose --profile volumetrie build volumetrie
#     docker compose run --rm volumetrie volumetrie/run_s5.sh
# --secours : n'utilise pas le réseau (Spark sur l'extrait fictif) ; le streaming
# distant n'est alors PAS validé.
set -euo pipefail
cd "$(dirname "$0")/.."

limite=200000
secours=0
while [ $# -gt 0 ]; do
  case "$1" in
    --limite) limite="$2"; shift 2 ;;
    --secours) secours=1; shift ;;
    *) echo "Option inconnue : $1" >&2; exit 2 ;;
  esac
done

export HF_HUB_DISABLE_XET=1
filtre_spark='^(WARNING: Using incubator|Using Spark|Setting default log|To adjust logging|.* WARN NativeCodeLoader)'
horodatage=$(date +%Y%m%d-%H%M%S)

echo "== Diagnostic Spark"
python volumetrie/spark/verifier.py 2>&1 | grep -v -E "$filtre_spark"

if [ "$secours" -eq 1 ]; then
  echo "== Mode secours : streaming distant NON validé"
  python volumetrie/spark/pipeline.py --entree volumetrie/secours/trajets_fictifs.jsonl \
    "volumetrie/data/sorties/secours-$horodatage" 2>&1 | grep -v -E "$filtre_spark"
else
  echo "== M1 · fiche source (métadonnées + pied de page Parquet)"
  python volumetrie/hf_datasets/acces.py --infos
  python volumetrie/hf_datasets/fiche_source.py --json volumetrie/resultats/01_fiche_source.json > /dev/null
  echo "== M2 · streaming borné ($limite enregistrements)"
  python volumetrie/streaming/extraire.py --limite "$limite"
  echo "== M3 · contrôle qualité -> entrée Spark"
  python volumetrie/streaming/controler.py
  echo "== M4 · pipeline Spark"
  python volumetrie/spark/pipeline.py "volumetrie/data/sorties/yellow-2024-01-$horodatage" 2>&1 \
    | grep -v -E "$filtre_spark" > volumetrie/resultats/05_spark_pipeline.txt
  grep -E '^(Avant|Lignes lues|Trajets|Relecture|OK)' volumetrie/resultats/05_spark_pipeline.txt
fi

echo "== M5 · dossier publication/ (v1, données synthétiques)"
python volumetrie/publication/preparer.py --version 1
echo "Publication Hub : voir volumetrie/SOLUTION_S5.md, section M5 (hf auth login, upload v1/v2)."
