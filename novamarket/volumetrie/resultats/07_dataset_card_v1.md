---
pretty_name: NovaMarket S5 · trajets de taxi synthétiques enrichis (exercice)
license: other
license_name: usage-pedagogique
language:
  - fr
tags:
  - education
  - synthetic
  - tabular
size_categories:
  - n<1K
configs:
  - config_name: default
    data_files: trajets_synthetiques.parquet
---

# NovaMarket S5 · trajets de taxi synthétiques enrichis

Jeu **synthétique** publié pour l'exercice S5 (Hugging Face Hub) du projet NovaMarket.
Il reprend le schéma de l'extraction réelle (`Start_Zone`, `Trip_Distance`, `Trip_Duration`)
sans en contenir aucune ligne.

- **Provenance des trajets** : `volumetrie/secours/trajets_fictifs.jsonl`, données fictives
  fournies par le kit pédagogique S5 (6 lignes). Aucun passager, aucun horodatage.
- **Provenance des zones** : table officielle TLC *Taxi Zone Lookup* (`zones.csv`,
  265 zones), publiée sur NYC Open Data.
- **Pourquoi pas les données réelles** : le miroir `DinoPonjevic/NYC_TaxiData`
  (révision `5941adbf8c0b9930e47002dc3103de3f9291360d`) déclare une licence `unknown` ;
  ses lignes sont lues et analysées en local mais jamais republiées.
- **Conditions d'usage** : exercice pédagogique uniquement ; les valeurs n'ont aucune
  valeur statistique et ne décrivent aucun trajet réel.

## Colonnes et unités

Grain : **un trajet synthétique** par ligne. Fichier : `trajets_synthetiques.parquet` (Parquet, 5 lignes).

| Colonne | Type | Unité / domaine | Manquants |
|---|---|---|---|
| `ligne_source` | int32 | rang (0-based) dans `trajets_fictifs.jsonl` | non |
| `zone_depart` | int32 | `LocationID` TLC (1–265) | non |
| `arrondissement` | string | `Borough` TLC, ou `Zone inconnue` hors référentiel | non |
| `zone` | string | nom de zone TLC (non unique : ne pas l'utiliser comme clé) | oui (zone hors référentiel) |
| `distance_miles` | float64 | miles | non |
| `duree_s` | int32 | secondes | non |

Plage temporelle : sans objet (aucun horodatage dans le jeu synthétique).

## Extraction et qualité

- Lignes parcourues : 6 · gardées : 5 · écartées : 1.
- Écartées : ligne 4 (distance_non_positive).
- Règles (identiques au contrôle M3 de l'extraction réelle) : 0 < distance ≤ 100 miles,
  0 < durée ≤ 21 600 s, vitesse moyenne ≤ 80 mph ; clé de jointure `zone_depart` = `LocationID`,
  unique dans la table de zones (265 clés distinctes), jointure gauche sans multiplication.
- Limites : 6 trajets fictifs, aucune représentativité ; ce jeu sert à éprouver la
  publication, la Dataset Card et le versionnement, pas à l'analyse.
- Reproduction (depuis `novamarket/`) :
  `python volumetrie/publication/preparer.py --version 1`

## Révisions

- **v1 — révision initiale.** 5 trajets synthétiques conformes, joints aux zones TLC ;
  le trajet en zone 999 (absente du référentiel) est conservé avec `arrondissement = Zone inconnue`.
- v2 — à venir.
