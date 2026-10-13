"""Préparation du fichier de configuration : création, écriture, questions.

Les réponses aux questions sont injectées : aucun test ne demande quoi que ce
soit au clavier, et aucun mot de passe n'apparaît dans la sortie.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from app import env, setup


def answers(mapping):
    """Fonction de saisie qui répond selon un mot-clé de la question posée."""
    def getpass_fn(prompt=""):
        low = prompt.lower()
        for needle, value in mapping.items():
            if needle.lower() in low:
                return value
        return ""
    return getpass_fn


class FileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / ".env"
        self.example = Path(self.tmp.name) / ".env.example"
        self.example.write_text("# modèle\n# LC_PASSWORD_HASH=scrypt$1$2$3$4\n"
                                "# CARTESIA_API_KEY=...\n", encoding="utf-8")

    def test_creates_the_file_from_the_example_once(self):
        self.assertTrue(setup.create_from_example(self.path, self.example))
        self.assertIn("LC_PASSWORD_HASH", self.path.read_text(encoding="utf-8"))
        if os.name == "posix":
            self.assertEqual(oct(self.path.stat().st_mode)[-3:], "600", "fichier de secrets")
        self.assertFalse(setup.create_from_example(self.path, self.example), "jamais écrasé")

    def test_writes_the_value_on_the_commented_model_line(self):
        setup.create_from_example(self.path, self.example)
        setup.set_value("LC_PASSWORD_HASH", "scrypt$9$9$9$abc", self.path)
        body = self.path.read_text(encoding="utf-8")
        self.assertIn("LC_PASSWORD_HASH=scrypt$9$9$9$abc", body)
        self.assertNotIn("# LC_PASSWORD_HASH", body)
        self.assertEqual(env.read(self.path)["LC_PASSWORD_HASH"], "scrypt$9$9$9$abc")

    def test_a_stale_duplicate_does_not_win(self):
        self.path.write_text("LC_PASSWORD_HASH=ancien\n# LC_PASSWORD_HASH=vieux\n", encoding="utf-8")
        setup.set_value("LC_PASSWORD_HASH", "scrypt$1$2$3$4", self.path)
        self.assertEqual(env.read(self.path)["LC_PASSWORD_HASH"], "scrypt$1$2$3$4")

    def test_appends_a_key_the_example_does_not_know(self):
        self.example.write_text("# rien\n", encoding="utf-8")
        setup.create_from_example(self.path, self.example)
        setup.set_value("CARTESIA_API_KEY", "sk_car_test", self.path)
        self.assertEqual(env.read(self.path)["CARTESIA_API_KEY"], "sk_car_test")


class InteractiveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / ".env"
        self.lines = []

    def run_setup(self, mapping, interactive=True):
        return setup.main(self.path, interactive=interactive,
                          getpass_fn=answers(mapping), echo=self.lines.append)

    def test_asks_for_both_and_writes_them(self):
        self.run_setup({"mot de passe": "testpw", "Cartesia": "sk_car_abcdef"})
        values = env.read(self.path)
        self.assertTrue(values["LC_PASSWORD_HASH"].startswith("scrypt$"))
        self.assertEqual(values["CARTESIA_API_KEY"], "sk_car_abcdef")
        joined = "\n".join(self.lines)
        self.assertIn(setup.CARTESIA_KEYS_URL, joined, "l'adresse où créer la clé est donnée")
        # Le mot de passe et la clé ne doivent jamais être réaffichés.
        self.assertNotIn("testpw", joined)
        self.assertNotIn("sk_car_abcdef", joined)

    def test_empty_answers_leave_the_file_alone(self):
        self.run_setup({"mot de passe": "", "Cartesia": ""})
        self.assertEqual(env.read(self.path), {})
        self.assertIn("laissé vide", "\n".join(self.lines))

    def test_nothing_is_asked_when_everything_is_configured(self):
        self.path.write_text("LC_PASSWORD_HASH=scrypt$1$2$3$4\nCARTESIA_API_KEY=sk_car_x\n",
                             encoding="utf-8")
        self.run_setup({"mot de passe": "ne devrait pas servir"})
        self.assertNotIn("Préparation du coach", "\n".join(self.lines))
        self.assertEqual(env.read(self.path)["CARTESIA_API_KEY"], "sk_car_x")

    def test_without_a_terminal_it_reports_instead_of_asking(self):
        self.run_setup({}, interactive=False)
        joined = "\n".join(self.lines)
        self.assertNotIn("Préparation du coach", joined)
        self.assertIn("à configurer", joined)
        self.assertEqual(env.read(self.path), {}, "rien n'est écrit sans réponse")

    def test_a_refused_key_is_kept_with_a_warning(self):
        with patch("httpx.get", return_value=MagicMock(status_code=401)):
            self.run_setup({"mot de passe": "testpw", "Cartesia": "sk_car_refusee"})
        self.assertEqual(env.read(self.path)["CARTESIA_API_KEY"], "sk_car_refusee")
        self.assertIn("401", "\n".join(self.lines))
        self.assertNotIn("sk_car_refusee", "\n".join(self.lines))


class CheckTest(unittest.TestCase):
    def test_valid_key_refusal_and_no_way_to_check(self):
        with patch("httpx.get", return_value=MagicMock(status_code=200)):
            self.assertEqual(setup.check_cartesia("sk_car_ok"), "")
        with patch("httpx.get", return_value=MagicMock(status_code=403)):
            self.assertIn("403", setup.check_cartesia("sk_car_ko"))
        with patch("httpx.get", side_effect=OSError("réseau coupé")):
            self.assertIsNone(setup.check_cartesia("sk_car_ko"), "non vérifiable, pas « valide »")
        with patch.dict(sys.modules, {"httpx": None}):
            self.assertIsNone(setup.check_cartesia("sk_car_ko"))

    def test_status_reports_what_is_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            self.assertEqual(setup.status(path), {"password": False, "cartesia": False})
            path.write_text("LC_PASSWORD_HASH=scrypt$1$2$3$4\n", encoding="utf-8")
            self.assertEqual(setup.status(path), {"password": True, "cartesia": False})


if __name__ == "__main__":
    unittest.main()
