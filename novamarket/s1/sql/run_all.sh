#!/usr/bin/env bash
# Rejoue toute la chaîne S1 depuis novamarket/ : ./s1/sql/run_all.sh
set -euo pipefail
cd "$(dirname "$0")/../.."
docker compose up -d --wait postgres
for f in 00_connexion 01_schema 02_import 03_controles 04_indicateurs 05_anomalies 06_normalisation; do
  echo "################ $f"
  docker compose exec -T postgres psql -X -q -v ON_ERROR_STOP=1 -U atelier -d novamarket -f "/s1/sql/$f.sql"
done
