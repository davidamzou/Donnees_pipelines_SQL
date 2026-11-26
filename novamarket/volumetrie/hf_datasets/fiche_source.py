"""M1 · Fiche source : métadonnées du dépôt et pied de page Parquet de la partition.

Ne parcourt aucune ligne : seules l'API de métadonnées du Hub et le pied de page
(footer) du fichier Parquet sont lus (lecture par plages HTTP, quelques Ko).
Usage (depuis novamarket/) : python volumetrie/hf_datasets/fiche_source.py [--json SORTIE]
"""
import argparse
import json
from collections import Counter
from pathlib import Path

import pyarrow.parquet as pq
from huggingface_hub import HfApi, HfFileSystem

SOURCE = json.loads(Path(__file__).with_name("source.json").read_text(encoding="utf-8"))


def fiche():
    info = HfApi().dataset_info(SOURCE["repo"], revision=SOURCE["revision"], files_metadata=True, token=False)
    parquets = {e.rfilename: e.size for e in info.siblings if e.rfilename.endswith(".parquet")}
    # Organisation annee/type/mois : volume par type de taxi.
    par_type = Counter()
    for nom, taille in parquets.items():
        par_type[nom.split("/")[1]] += taille

    fs = HfFileSystem(token=False)
    chemin = f"datasets/{SOURCE['repo']}@{SOURCE['revision']}/{SOURCE['shard']}"
    with fs.open(chemin, "rb", block_size=1 << 20) as f:
        meta = pq.ParquetFile(f).metadata
        schema = meta.schema.to_arrow_schema()
    colonnes_rg0 = {meta.row_group(0).column(i).path_in_schema: meta.row_group(0).column(i)
                    for i in range(meta.num_columns)}
    stats = {}
    for col in SOURCE["columns"]:
        s = colonnes_rg0[col].statistics
        stats[col] = None if s is None or not s.has_min_max else {
            "min_groupe_0": s.min, "max_groupe_0": s.max, "nuls_groupe_0": s.null_count}
    return {
        "depot": SOURCE["repo"],
        "revision": info.sha,
        "revision_conforme": info.sha == SOURCE["revision"],
        "licence_miroir": info.card_data.license if info.card_data else None,
        "fichiers_parquet": len(parquets),
        "octets_depot": sum(parquets.values()),
        "octets_par_type": dict(sorted(par_type.items())),
        "partition": SOURCE["shard"],
        "octets_partition": parquets[SOURCE["shard"]],
        "lignes_partition": meta.num_rows,
        "groupes_de_lignes": meta.num_row_groups,
        "lignes_groupe_0": meta.row_group(0).num_rows,
        "schema_partition": {champ.name: str(champ.type) for champ in schema},
        "colonnes_projetees": SOURCE["columns"],
        "statistiques_groupe_0": stats,
        "createur_parquet": meta.created_by,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", type=Path, help="Écrire aussi la fiche dans ce fichier")
    args = parser.parse_args()
    resultat = fiche()
    texte = json.dumps(resultat, ensure_ascii=False, indent=2, default=str)
    print(texte)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(texte + "\n", encoding="utf-8")
