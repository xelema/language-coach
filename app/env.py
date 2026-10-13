"""Lecture du fichier `.env`, sans dépendance.

`./run.sh` lance l'application directement : un `.env` posé à côté de `run.sh`
n'aurait jamais été lu (dans le projet d'origine, c'était le compose Docker qui
le chargeait). Il est lu ici, une fois, à l'import du paquet. Les variables déjà
présentes dans l'environnement gardent la priorité : exporter une valeur dans le
shell reste la façon de la surcharger.

Le contenu est toléré tel qu'un éditeur Windows le produit : BOM, fins de ligne
CRLF, fichier enregistré en UTF-16, guillemets autour de la valeur, `export ` en
début de ligne, lignes vides ou commentées.
"""
import os
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent / ".env"


def parse(text: str) -> dict:
    """Les paires clé=valeur du texte, en ignorant commentaires et lignes vides."""
    values = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def read(path: Path) -> dict:
    """Le contenu du fichier, quelle que soit l'encodage d'un éditeur courant."""
    data = Path(path).read_bytes()
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):  # UTF-16 avec BOM (Notepad, PowerShell)
        return parse(data.decode("utf-16"))
    return parse(data.decode("utf-8-sig", errors="replace"))


def load_env(path=None, environ=None) -> dict:
    """Charge le .env dans l'environnement, sans écraser ce qui est déjà défini."""
    environ = os.environ if environ is None else environ
    path = Path(path) if path else DEFAULT_PATH
    if not path.is_file():
        return {}
    values = read(path)
    for key, value in values.items():
        environ.setdefault(key, value)
    return values
