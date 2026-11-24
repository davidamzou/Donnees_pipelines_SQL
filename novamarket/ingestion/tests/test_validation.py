"""Tests unitaires des règles de validation (sans réseau ni API).

    python -m unittest discover -s ingestion/tests -v
"""
import sys
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from validation import Validateur, charger_catalogue, controler_offre  # noqa: E402

CATALOGUE = frozenset(range(1, 25))


def offre(**modifs):
    base = dict(offer_id="O001", supplier_id="F01", product_id=1, price_cents=625,
                currency="EUR", available_units=2, observed_on="2026-11-24")
    base.update(modifs)
    return base


class ControlesOffre(unittest.TestCase):
    def test_offre_conforme(self):
        self.assertEqual(controler_offre(offre(), CATALOGUE), [])

    def test_champ_manquant(self):
        o = offre()
        del o["supplier_id"]
        self.assertEqual(controler_offre(o, CATALOGUE), ["champ_manquant:supplier_id"])

    def test_champ_nul(self):
        self.assertIn("champ_nul:price_cents", controler_offre(offre(price_cents=None), CATALOGUE))

    def test_prix_texte(self):
        self.assertEqual(controler_offre(offre(price_cents="inconnu"), CATALOGUE),
                         ["type_invalide:price_cents"])

    def test_booleen_et_flottant_refuses(self):
        self.assertIn("type_invalide:price_cents", controler_offre(offre(price_cents=True), CATALOGUE))
        self.assertIn("type_invalide:available_units",
                      controler_offre(offre(available_units=2.0), CATALOGUE))

    def test_valeurs_negatives(self):
        motifs = controler_offre(offre(price_cents=-1, available_units=-3), CATALOGUE)
        self.assertEqual(motifs, ["valeur_negative:price_cents", "valeur_negative:available_units"])

    def test_zero_autorise(self):
        self.assertEqual(controler_offre(offre(price_cents=0, available_units=0), CATALOGUE), [])

    def test_produit_hors_catalogue(self):
        self.assertEqual(controler_offre(offre(product_id=9999), CATALOGUE), ["produit_hors_catalogue"])

    def test_product_id_texte(self):
        self.assertEqual(controler_offre(offre(product_id="1"), CATALOGUE), ["type_invalide:product_id"])

    def test_devise(self):
        self.assertEqual(controler_offre(offre(currency="USD"), CATALOGUE), ["devise_invalide"])

    def test_fournisseur_inconnu(self):
        self.assertEqual(controler_offre(offre(supplier_id="F09"), CATALOGUE), ["fournisseur_inconnu"])

    def test_dates(self):
        self.assertEqual(controler_offre(offre(observed_on="24/11/2026"), CATALOGUE),
                         ["format_invalide:observed_on"])
        self.assertEqual(controler_offre(offre(observed_on="2026-02-30"), CATALOGUE),
                         ["date_inexistante:observed_on"])

    def test_plusieurs_fautes_relevees(self):
        o = offre(price_cents="x", currency="USD")
        del o["offer_id"]
        self.assertEqual(len(controler_offre(o, CATALOGUE)), 3)

    def test_objet_non_dict(self):
        self.assertEqual(controler_offre(["O001"], CATALOGUE), ["structure:objet_attendu"])


class Doublons(unittest.TestCase):
    def test_premiere_occurrence_conservee(self):
        v = Validateur(CATALOGUE)
        self.assertTrue(v.examiner(1, 1, offre()))
        self.assertFalse(v.examiner(6, 4, offre()))
        self.assertEqual(len(v.valides), 1)
        self.assertEqual(v.rejets[0]["motifs"], ["doublon:offer_id"])
        self.assertEqual(v.rejets[0]["premiere_occurrence"], {"page": 1, "position": 1})

    def test_offre_rejetee_ne_bloque_pas_la_suivante(self):
        v = Validateur(CATALOGUE)
        self.assertFalse(v.examiner(1, 1, offre(price_cents="x")))
        self.assertTrue(v.examiner(1, 2, offre()))

    def test_champs_supplementaires_retires(self):
        v = Validateur(CATALOGUE)
        v.examiner(1, 1, offre(commentaire="interne"))
        self.assertNotIn("commentaire", v.valides[0])
        self.assertEqual(list(v.valides[0]),
                         ["offer_id", "supplier_id", "product_id", "price_cents",
                          "currency", "available_units", "observed_on"])


class Catalogue(unittest.TestCase):
    def test_catalogue_s2(self):
        chemin = RACINE.parent / "s2" / "donnees" / "products.csv"
        self.assertEqual(charger_catalogue(chemin), frozenset(range(1, 25)))


if __name__ == "__main__":
    unittest.main()
