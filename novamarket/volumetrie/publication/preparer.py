"""M5 · Prépare le dossier publication/ (Dataset Card + un Parquet) pour le Hub.

Seules des données AUTORISÉES sont publiées : les trajets SYNTHÉTIQUES du kit
(volumetrie/secours/trajets_fictifs.jsonl) enrichis par la table de zones
officielle TLC (volumetrie/secours/zones.csv, NYC Open Data). Aucune ligne du
miroir DinoPonjevic/NYC_TaxiData (licence « unknown ») n'est republiée.

  --version 1 : trajets synthétiques conformes au contrôle M3, joints aux zones ;
                le trajet en zone 999 (absente du référentiel) est conservé avec
                arrondissement « Zone inconnue ».
  --version 2 : changement documenté : le trajet hors référentiel est retiré
                (zone_connue = faux) et une colonne vitesse_mph est ajoutée.

Le dossier ne doit contenir que README.md et trajets_synthetiques.parquet : tout
autre fichier provoque un refus (pas de token, de cache ou de brouillon publié).
Usage (depuis novamarket/) : python volumetrie/publication/preparer.py --version 1
"""
import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "streaming"))
from controler import motif_rejet  # noqa: E402  (mêmes règles qu'en M3)

TRAJETS = RACINE / "secours" / "trajets_fictifs.jsonl"
ZONES = RACINE / "secours" / "zones.csv"
FICHIER = "trajets_synthetiques.parquet"
AUTORISES = {"README.md", FICHIER}


def lignes(version):
    with ZONES.open(encoding="utf-8", newline="") as f:
        zones = {int(z["LocationID"]): z for z in csv.DictReader(f)}
    lues, ecartees, sortie = 0, [], []
    with TRAJETS.open(encoding="utf-8") as f:
        for numero, brut in enumerate(f):
            if not brut.strip():
                continue
            lues += 1
            enr = json.loads(brut)
            motif = motif_rejet(enr)
            zone = zones.get(enr["Start_Zone"])
            if motif is None and version == 2 and zone is None:
                motif = "zone_hors_referentiel"
            if motif:
                ecartees.append({"ligne_source": numero, "motif": motif})
                continue
            ligne = {"ligne_source": numero, "zone_depart": enr["Start_Zone"],
                     "arrondissement": zone["Borough"] if zone else "Zone inconnue",
                     "zone": zone["Zone"] if zone else None,
                     "distance_miles": float(enr["Trip_Distance"]),
                     "duree_s": int(enr["Trip_Duration"])}
            if version == 2:
                ligne["vitesse_mph"] = round(ligne["distance_miles"] / (ligne["duree_s"] / 3600), 2)
            sortie.append(ligne)
    return lues, ecartees, sortie


def schema(version):
    champs = [("ligne_source", pa.int32()), ("zone_depart", pa.int32()), ("arrondissement", pa.string()),
              ("zone", pa.string()), ("distance_miles", pa.float64()), ("duree_s", pa.int32())]
    if version == 2:
        champs.append(("vitesse_mph", pa.float64()))
    return pa.schema(champs)


CARTE = """---
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
    data_files: {fichier}
---

# NovaMarket S5 · trajets de taxi synthétiques enrichis

Jeu **synthétique** publié pour l'exercice S5 (Hugging Face Hub) du projet NovaMarket.
Il reprend le schéma de l'extraction réelle (`Start_Zone`, `Trip_Distance`, `Trip_Duration`)
sans en contenir aucune ligne.

- **Provenance des trajets** : `volumetrie/secours/trajets_fictifs.jsonl`, données fictives
  fournies par le kit pédagogique S5 ({lues} lignes). Aucun passager, aucun horodatage.
- **Provenance des zones** : table officielle TLC *Taxi Zone Lookup* (`zones.csv`,
  265 zones), publiée sur NYC Open Data.
- **Pourquoi pas les données réelles** : le miroir `DinoPonjevic/NYC_TaxiData`
  (révision `5941adbf8c0b9930e47002dc3103de3f9291360d`) déclare une licence `unknown` ;
  ses lignes sont lues et analysées en local mais jamais republiées.
- **Conditions d'usage** : exercice pédagogique uniquement ; les valeurs n'ont aucune
  valeur statistique et ne décrivent aucun trajet réel.

## Colonnes et unités

Grain : **un trajet synthétique** par ligne. Fichier : `{fichier}` (Parquet, {n} lignes).

| Colonne | Type | Unité / domaine | Manquants |
|---|---|---|---|
| `ligne_source` | int32 | rang (0-based) dans `trajets_fictifs.jsonl` | non |
| `zone_depart` | int32 | `LocationID` TLC (1–265) | non |
| `arrondissement` | string | `Borough` TLC, ou `Zone inconnue` hors référentiel | non |
| `zone` | string | nom de zone TLC (non unique : ne pas l'utiliser comme clé) | {zone_nulle} |
| `distance_miles` | float64 | miles | non |
| `duree_s` | int32 | secondes | non |
{ligne_vitesse}
Plage temporelle : sans objet (aucun horodatage dans le jeu synthétique).

## Extraction et qualité

- Lignes parcourues : {lues} · gardées : {n} · écartées : {nb_ecartees}.
- Écartées : {ecartees}.
- Règles (identiques au contrôle M3 de l'extraction réelle) : 0 < distance ≤ 100 miles,
  0 < durée ≤ 21 600 s, vitesse moyenne ≤ 80 mph ; clé de jointure `zone_depart` = `LocationID`,
  unique dans la table de zones (265 clés distinctes), jointure gauche sans multiplication.
{regle_v2}- Limites : 6 trajets fictifs, aucune représentativité ; ce jeu sert à éprouver la
  publication, la Dataset Card et le versionnement, pas à l'analyse.
- Reproduction (depuis `novamarket/`) :
  `python volumetrie/publication/preparer.py --version {version}`

## Révisions

- **v1 — révision initiale.** 5 trajets synthétiques conformes, joints aux zones TLC ;
  le trajet en zone 999 (absente du référentiel) est conservé avec `arrondissement = Zone inconnue`.
{revision_v2}"""

REVISION_V2 = """- **v2 — deuxième révision.** Le trajet `ligne_source = 5` (zone 999, absente des 265 zones
  TLC) est retiré : une zone hors référentiel ne peut pas être rattachée à un arrondissement et
  faussait la répartition (1 trajet sur 5 en « Zone inconnue »). Ajout de la colonne calculée
  `vitesse_mph = distance_miles / (duree_s / 3600)`, arrondie au centième. 5 → 4 lignes.
"""


def preparer(version, dossier):
    dossier.mkdir(parents=True, exist_ok=True)
    intrus = sorted(p.name for p in dossier.iterdir() if p.name not in AUTORISES)
    if intrus:
        sys.exit(f"Refus : {dossier} contient des fichiers non autorisés : {', '.join(intrus)}")
    lues, ecartees, donnees = lignes(version)
    table = pa.Table.from_pylist(donnees, schema=schema(version))
    pq.write_table(table, dossier / FICHIER)
    carte = CARTE.format(
        fichier=FICHIER, lues=lues, n=len(donnees), nb_ecartees=len(ecartees), version=version,
        ecartees=", ".join(f"ligne {e['ligne_source']} ({e['motif']})" for e in ecartees) or "aucune",
        zone_nulle="oui (zone hors référentiel)" if any(d["zone"] is None for d in donnees) else "non",
        ligne_vitesse="| `vitesse_mph` | float64 | miles par heure, calculée | non |\n" if version == 2 else "",
        regle_v2="- v2 : les trajets dont la zone est absente du référentiel TLC sont écartés.\n"
                 if version == 2 else "",
        revision_v2=REVISION_V2 if version == 2 else "- v2 — à venir.\n")
    (dossier / "README.md").write_text(carte, encoding="utf-8")
    for nom in sorted(AUTORISES):
        empreinte = hashlib.sha256((dossier / nom).read_bytes()).hexdigest()
        print(f"{nom:32s} {(dossier / nom).stat().st_size:>6d} o  sha256={empreinte[:16]}…")
    print(f"v{version} : {lues} lues, {len(donnees)} publiées, {len(ecartees)} écartées -> {dossier}")
    print(table.to_pandas().to_string(index=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", type=int, choices=(1, 2), required=True)
    parser.add_argument("--dossier", type=Path, default=RACINE.parent / "publication")
    a = parser.parse_args()
    preparer(a.version, a.dossier)
