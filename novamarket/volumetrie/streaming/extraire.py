"""M2 · Lecture en streaming bornée de la partition Yellow 2024-01 et extraction JSONL.

Réutilise volumetrie/hf_datasets/acces.py (révision épinglée, colonnes projetées,
pas de préchargement Parquet, lots courts). Aucune ligne n'est matérialisée en
mémoire : chaque enregistrement est lu, compté, contrôlé puis écrit ou rejeté.

Règle de validité structurelle (M2) — un enregistrement est retenu si :
  - les trois champs Start_Zone, Trip_Distance, Trip_Duration sont présents ;
  - aucun n'est nul ;
  - Start_Zone et Trip_Duration sont des entiers, Trip_Distance un nombre fini.
Les règles métier (bornes, cohérence distance/durée, zones connues) relèvent de
M3 (controler.py) : M2 ne juge que la forme, pas la plausibilité.

Compteurs : parcourues = retenues + rejetées, comptées AVANT tout filtrage.
Le fichier est écrit sous un nom temporaire puis renommé : une extraction
interrompue ne laisse pas de JSONL incomplet passant pour valide.

Usage (depuis novamarket/) :
  HF_HUB_DISABLE_XET=1 python volumetrie/streaming/extraire.py --limite 200000
"""
import argparse
import hashlib
import json
import math
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "hf_datasets"))
from acces import SOURCE, ouvrir  # noqa: E402

RACINE = Path(__file__).resolve().parents[1]


def chemin_lisible(chemin):
    """Chemin relatif à novamarket/ si possible (bilans comparables d'un poste à l'autre)."""
    try:
        return str(chemin.resolve().relative_to(RACINE.parent))
    except ValueError:
        return str(chemin)


def motif_rejet(ligne):
    """Renvoie None si l'enregistrement est structurellement valide, sinon le motif."""
    if set(ligne) != set(SOURCE["columns"]):
        return "colonnes_inattendues"
    zone, distance, duree = (ligne[c] for c in ("Start_Zone", "Trip_Distance", "Trip_Duration"))
    if zone is None or distance is None or duree is None:
        return "valeur_manquante"
    if isinstance(zone, bool) or not isinstance(zone, int):
        return "zone_non_entiere"
    if isinstance(duree, bool) or not isinstance(duree, int):
        return "duree_non_entiere"
    if isinstance(distance, bool) or not isinstance(distance, (int, float)) or not math.isfinite(distance):
        return "distance_non_numerique"
    return None


def extraire(limite, sortie, bilan_chemin):
    sortie.parent.mkdir(parents=True, exist_ok=True)
    partiel = sortie.with_name(sortie.name + ".partiel")
    compteurs = Counter()
    motifs = Counter()
    exemples_rejets = []
    debut = time.monotonic()
    statut, erreur = "en_cours", None
    flux = iter(ouvrir())
    try:
        with partiel.open("w", encoding="utf-8") as out:
            for rang, ligne in enumerate(flux):
                if rang >= limite:
                    break
                compteurs["parcourues"] += 1
                motif = motif_rejet(ligne)
                if motif:
                    compteurs["rejetees"] += 1
                    motifs[motif] += 1
                    if len(exemples_rejets) < 5:
                        exemples_rejets.append({"ligne_source": rang, "motif": motif, **ligne})
                    continue
                compteurs["retenues"] += 1
                out.write(json.dumps({"ligne_source": rang, **ligne}, separators=(",", ":")) + "\n")
        partiel.replace(sortie)
        statut = "termine"
    except BaseException as exc:  # y compris Ctrl+C : on consigne puis on relance
        statut, erreur = "interrompu", f"{type(exc).__name__}: {exc}"
        raise
    finally:
        flux.close()  # fermeture explicite du flux HTTP/Parquet, même en cas d'erreur
        duree = time.monotonic() - debut
        bilan = {
            "etape": "M2_extraction_streaming",
            "statut": statut,
            "erreur": erreur,
            "horodatage_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": {k: SOURCE[k] for k in ("repo", "revision", "shard", "columns")},
            "limite": limite,
            "parcourues": compteurs["parcourues"],
            "retenues": compteurs["retenues"],
            "rejetees": compteurs["rejetees"],
            "motifs_rejet": dict(motifs),
            "exemples_rejets": exemples_rejets,
            "secondes": round(duree, 1),
            "lignes_par_seconde": round(compteurs["parcourues"] / duree) if duree else None,
            "sortie": chemin_lisible(sortie) if statut == "termine" else None,
        }
        if statut == "termine":
            bilan["sha256_sortie"] = hashlib.sha256(sortie.read_bytes()).hexdigest()
            bilan["octets_sortie"] = sortie.stat().st_size
        assert bilan["parcourues"] == bilan["retenues"] + bilan["rejetees"]
        bilan_chemin.parent.mkdir(parents=True, exist_ok=True)
        bilan_chemin.write_text(json.dumps(bilan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({k: bilan[k] for k in ("statut", "parcourues", "retenues", "rejetees",
                                                 "motifs_rejet", "secondes", "lignes_par_seconde")},
                         ensure_ascii=False))
    return bilan


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--limite", type=int, default=200_000, help="Nombre maximal d'enregistrements parcourus")
    parser.add_argument("--sortie", type=Path, default=RACINE / "data" / "extraction" / "trajets_extraits.jsonl")
    parser.add_argument("--bilan", type=Path, default=RACINE / "resultats" / "02_bilan_extraction.json")
    args = parser.parse_args()
    if args.limite <= 0:
        parser.error("--limite doit être strictement positive")
    extraire(args.limite, args.sortie, args.bilan)
