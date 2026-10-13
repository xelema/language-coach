"""Rendu des gabarits de prompt.

Les fichiers de `coach/` sont des gabarits : `{{variable}}` est remplacé par la
valeur du contexte (langue, profil, état du carnet). Un paquet de langue
incomplet ne casse rien — une variable sans valeur disparaît — donc ajouter une
langue ne demande jamais de toucher aux gabarits.
"""
import re
from pathlib import Path

PROMPT_DIR = Path(__file__).resolve().parent.parent / "coach"
PLACEHOLDER = re.compile(r"\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}")


def render(text: str, values: dict) -> str:
    return PLACEHOLDER.sub(lambda m: str(values.get(m.group(1), "")), text)


def load(names, values: dict) -> str:
    """Concatène les gabarits présents, dans l'ordre donné."""
    blocks = []
    for name in names:
        path = PROMPT_DIR / name
        if path.is_file():
            blocks.append(render(path.read_text(encoding="utf-8"), values).strip())
    return "\n\n".join(blocks)


def missing(values: dict, names=None) -> set[str]:
    """Variables utilisées par les gabarits que le contexte ne fournit pas :
    sert de garde-fou en test, jamais à l'exécution."""
    used: set[str] = set()
    for path in sorted(PROMPT_DIR.glob("*.md")):
        if names and path.name not in names:
            continue
        used |= set(PLACEHOLDER.findall(path.read_text(encoding="utf-8")))
    return {name for name in used if name not in values}
