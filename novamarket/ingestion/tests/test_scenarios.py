"""Tests d'intégration : le collecteur contre l'API locale (ignorés si absente).

    docker compose up -d --build --wait fournisseur
    python -m unittest discover -s ingestion/tests -v

Chaque test écrit dans un dossier temporaire avec un `run` neuf : les données
du groupe dans `ingestion/data/` ne sont pas touchées.
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

BASE_URL = os.environ.get("NOVAMARKET_API_URL",
                          f"http://127.0.0.1:{os.environ.get('NOVAMARKET_API_PORT', '18080')}")


def api_disponible() -> bool:
    try:
        with urlopen(BASE_URL + "/health", timeout=2) as reponse:
            return json.load(reponse) == {"status": "ok"}
    except OSError:
        return False


def lire_jsonl(chemin: Path) -> list[dict]:
    with open(chemin, encoding="utf-8") as f:
        return [json.loads(ligne) for ligne in f]


@unittest.skipUnless(api_disponible(), f"API fournisseur absente sur {BASE_URL}")
class Scenarios(unittest.TestCase):
    def setUp(self):
        import collecteur
        self.collecteur = collecteur
        self.dossier = Path(tempfile.mkdtemp(prefix="novamarket-s3-"))

    def lancer(self, scenario: str, *options: str) -> tuple[int, dict]:
        run = f"test-{scenario}-{uuid.uuid4().hex[:8]}"
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            code = self.collecteur.main(["--base-url", BASE_URL, "--scenario", scenario,
                                         "--run", run, "--sortie", str(self.dossier), *options])
        bilan = json.loads((self.dossier / "bilans" / f"{run}.json").read_text(encoding="utf-8"))
        return code, bilan

    def test_clean_complet(self):
        code, bilan = self.lancer("clean")
        self.assertEqual(code, 0)
        self.assertEqual((bilan["pages_recues"], bilan["requetes_http"], bilan["lignes_valides"]), (6, 6, 24))
        self.assertTrue(all(bilan["controles"].values()))

    def test_atelier_20_valides_4_rejets(self):
        code, bilan = self.lancer("atelier", "--concurrence", "2")
        self.assertEqual(code, 0)
        self.assertEqual((bilan["lignes_examinees"], bilan["lignes_valides"], bilan["lignes_rejetees"]),
                         (24, 20, 4))
        self.assertEqual(bilan["reprises"], 3)
        self.assertEqual(bilan["incidents"], {"http_429": 1, "json_invalide": 1, "timeout": 1})
        self.assertLessEqual(bilan["concurrence_observee"], 2)
        valides = lire_jsonl(self.dossier / "valid" / "offres.jsonl")
        self.assertEqual(len(valides), 20)
        self.assertEqual(len({o["offer_id"] for o in valides}), 20)
        rejets = lire_jsonl(self.dossier / "rejected" / f"{bilan['run']}.jsonl")
        self.assertEqual({(r["page"], r["position"]) for r in rejets}, {(2, 1), (3, 2), (5, 1), (6, 4)})

    def test_panne_ne_publie_rien(self):
        code, bilan = self.lancer("panne", "--tentatives", "2", "--backoff", "0.05")
        self.assertEqual(code, 1)
        self.assertEqual(bilan["statut"], "echec")
        self.assertFalse(bilan["publie"])
        self.assertEqual(bilan["pages_en_echec"], [6])
        self.assertFalse((self.dossier / "valid" / "offres.jsonl").exists())
        self.assertTrue((self.dossier / "raw" / f"{bilan['run']}.jsonl").exists())

    def test_panne_conserve_le_lot_precedent(self):
        self.lancer("clean")
        avant = (self.dossier / "valid" / "offres.jsonl").read_bytes()
        code, _ = self.lancer("panne", "--tentatives", "2", "--backoff", "0.05")
        self.assertEqual(code, 1)
        self.assertEqual((self.dossier / "valid" / "offres.jsonl").read_bytes(), avant)


if __name__ == "__main__":
    unittest.main()
