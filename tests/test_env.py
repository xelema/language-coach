"""Lecture du fichier `.env` : c'est lui qui porte le mot de passe du site.

Ce qui est vérifié ici, c'est ce qu'un éditeur (Notepad, PowerShell) produit
réellement : BOM, CRLF, UTF-16, guillemets, ligne commentée.
"""
import tempfile
import unittest
from pathlib import Path

from app import env


class ParseTest(unittest.TestCase):
    def test_parses_values_comments_quotes_and_export(self):
        values = env.parse(
            "# commentaire\n"
            "\n"
            "LC_PASSWORD_HASH=scrypt$16384$8$1$sel$empreinte\n"
            'export CARTESIA_API_KEY="oc_abc"\n'
            "LC_PORT=51121\n"
            "ligne sans egal\n")
        # Un hash scrypt contient des $ : aucune interpolation ne doit avoir lieu.
        self.assertEqual(values["LC_PASSWORD_HASH"], "scrypt$16384$8$1$sel$empreinte")
        self.assertEqual(values["CARTESIA_API_KEY"], "oc_abc")
        self.assertEqual(values["LC_PORT"], "51121")
        self.assertEqual(len(values), 3)

    def test_a_commented_password_stays_unset(self):
        self.assertEqual(env.parse("# LC_PASSWORD_HASH=scrypt$1$2$3$4\n"), {})

    def test_reads_crlf_bom_and_utf16(self):
        with tempfile.TemporaryDirectory() as tmp:
            crlf = Path(tmp) / "crlf.env"
            crlf.write_bytes("LC_PASSWORD_HASH=abc\r\nCARTESIA_API_KEY=xyz\r\n".encode("utf-8-sig"))
            self.assertEqual(env.read(crlf),
                             {"LC_PASSWORD_HASH": "abc", "CARTESIA_API_KEY": "xyz"})
            utf16 = Path(tmp) / "utf16.env"       # enregistrement Notepad « Unicode »
            utf16.write_text("LC_PASSWORD_HASH=abc\r\n", encoding="utf-16")
            self.assertEqual(env.read(utf16)["LC_PASSWORD_HASH"], "abc")

    def test_missing_file_is_not_an_error(self):
        self.assertEqual(env.load_env(Path(tempfile.gettempdir()) / "absent-xyz.env", {}), {})

    def test_load_fills_the_environment_without_overriding_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text("LC_PASSWORD_HASH=fichier\nLC_PORT=3111\n", encoding="utf-8")
            environ = {"LC_PORT": "9999"}
            env.load_env(path, environ)
            self.assertEqual(environ["LC_PASSWORD_HASH"], "fichier")
            self.assertEqual(environ["LC_PORT"], "9999", "ce qui est déjà exporté gagne")


if __name__ == "__main__":
    unittest.main()
