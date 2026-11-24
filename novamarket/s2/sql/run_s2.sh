#!/usr/bin/env bash
# Rejoue S2 depuis novamarket/ : ./s2/sql/run_s2.sh
# Pré-requis : base S1 chargée (./s1/sql/run_all.sh).
# Les sorties sont écrites dans s2/resultats/.
set -euo pipefail
cd "$(dirname "$0")/../.."
docker compose up -d --wait postgres
docker compose exec -T postgres mkdir -p /tmp/novamarket-s2
docker compose cp s2/donnees/. postgres:/tmp/novamarket-s2/
mkdir -p s2/resultats
for f in 10_catalogue 11_controles_catalogue 12_classements 13_evolution 14_segmentation 15_hierarchie; do
  echo "################ $f"
  docker compose exec -T postgres psql -X -v ON_ERROR_STOP=1 -U atelier -d novamarket \
    < "s2/sql/$f.sql" | tee "s2/resultats/$f.txt"
done
