"""Journal d'exécution (JSONL) et bilan de collecte.

Trois familles d'informations sont séparées :
- les événements techniques (requêtes, statuts, reprises, échecs) ;
- les anomalies de données (offres rejetées et motifs) ;
- les compteurs de fin d'exécution, rassemblés dans `Bilan`.
"""
from __future__ import annotations

import json
import logging
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

NOM_LOGGER = "novamarket.ingestion"
_ATTRIBUTS_STANDARD = set(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


def horodatage() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class FormatJSON(logging.Formatter):
    """Une ligne JSON par événement, avec les champs passés dans `extra`."""

    def format(self, record: logging.LogRecord) -> str:
        donnees = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "niveau": record.levelname,
            "evenement": record.getMessage(),
        }
        for cle, valeur in vars(record).items():
            if cle not in _ATTRIBUTS_STANDARD and not cle.startswith("_"):
                donnees[cle] = valeur
        return json.dumps(donnees, ensure_ascii=False, default=str)


class FormatConsole(logging.Formatter):
    """Lecture humaine : événement puis champs clé=valeur."""

    def format(self, record: logging.LogRecord) -> str:
        champs = " ".join(f"{cle}={valeur}" for cle, valeur in vars(record).items()
                          if cle not in _ATTRIBUTS_STANDARD and not cle.startswith("_"))
        return f"{record.levelname:<7} {record.getMessage()} {champs}".rstrip()


def configurer_journal(fichier: Path | None, verbeux: bool = False) -> logging.Logger:
    logger = logging.getLogger(NOM_LOGGER)
    logger.handlers.clear()
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    console = logging.StreamHandler(sys.stderr)
    console.setLevel(logging.DEBUG if verbeux else logging.INFO)
    console.setFormatter(FormatConsole())
    logger.addHandler(console)

    if fichier is not None:
        fichier.parent.mkdir(parents=True, exist_ok=True)
        disque = logging.FileHandler(fichier, mode="w", encoding="utf-8")
        disque.setLevel(logging.DEBUG)
        disque.setFormatter(FormatJSON())
        logger.addHandler(disque)
    return logger


@dataclass
class Bilan:
    """Compteurs vérifiables d'une exécution.

    `requetes_http` compte les essais HTTP (y compris ceux qui échouent) ;
    `lignes_*` comptent des offres. Les deux ne doivent pas être confondus.
    """
    run: str
    scenario: str
    concurrence_max: int
    tentatives_max: int
    timeout_s: float
    debut: str = field(default_factory=horodatage)
    fin: str | None = None
    duree_s: float | None = None
    statut: str = "en_cours"
    publie: bool = False
    pages_attendues: int | None = None
    pages_recues: int = 0
    pages_en_echec: list[int] = field(default_factory=list)
    requetes_http: int = 0
    reprises: int = 0
    concurrence_observee: int = 0
    tentatives_par_page: dict[int, int] = field(default_factory=dict)
    incidents: Counter = field(default_factory=Counter)
    lignes_examinees: int = 0
    lignes_valides: int = 0
    lignes_rejetees: int = 0
    motifs_rejet: Counter = field(default_factory=Counter)
    fichiers: dict[str, str] = field(default_factory=dict)
    erreur: str | None = None
    _t0: float = field(default_factory=time.perf_counter, repr=False)

    def cloturer(self, statut: str) -> None:
        self.statut = statut
        self.fin = horodatage()
        self.duree_s = round(time.perf_counter() - self._t0, 3)

    def controles(self) -> dict[str, bool]:
        """Égalités qui doivent tenir pour qu'un lot soit publiable."""
        return {
            "toutes_pages_recues": self.pages_attendues is not None
            and self.pages_recues == self.pages_attendues and not self.pages_en_echec,
            "lignes_equilibrees": self.lignes_examinees == self.lignes_valides + self.lignes_rejetees,
            "concurrence_respectee": self.concurrence_observee <= self.concurrence_max,
            "requetes_coherentes": self.requetes_http == sum(self.tentatives_par_page.values())
            and self.reprises == self.requetes_http - len(self.tentatives_par_page),
        }

    def en_dict(self) -> dict:
        donnees = {k: v for k, v in asdict(self).items() if not k.startswith("_")}
        donnees["tentatives_par_page"] = {str(k): v for k, v in sorted(self.tentatives_par_page.items())}
        donnees["incidents"] = dict(sorted(self.incidents.items()))
        donnees["motifs_rejet"] = dict(sorted(self.motifs_rejet.items()))
        donnees["controles"] = self.controles()
        return donnees

    def resume(self) -> str:
        controles = self.controles()
        lignes = [
            f"Run {self.run} · scénario {self.scenario} · statut {self.statut.upper()}"
            f" · publié={'oui' if self.publie else 'non'}",
            f"  Pages      : {self.pages_recues}/{self.pages_attendues or '?'} reçues"
            + (f", en échec {self.pages_en_echec}" if self.pages_en_echec else ""),
            f"  HTTP       : {self.requetes_http} requêtes, dont {self.reprises} reprises"
            f" · concurrence observée {self.concurrence_observee}/{self.concurrence_max}",
            f"  Incidents  : {dict(sorted(self.incidents.items())) or 'aucun'}",
            f"  Offres     : {self.lignes_examinees} examinées = {self.lignes_valides} valides"
            f" + {self.lignes_rejetees} rejetées",
            f"  Motifs     : {dict(sorted(self.motifs_rejet.items())) or 'aucun'}",
            f"  Durée      : {self.duree_s} s",
            "  Contrôles  : " + ", ".join(f"{k}={'ok' if v else 'KO'}" for k, v in controles.items()),
        ]
        if self.erreur:
            lignes.append(f"  Erreur     : {self.erreur}")
        return "\n".join(lignes)
