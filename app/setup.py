"""Préparation du fichier de configuration au premier lancement.

`./run.sh` appelle ce module avant de démarrer le serveur : il crée le fichier
`.env` à partir de `.env.example` s'il n'existe pas, puis demande ce qui manque
(mot de passe du site, clé Cartesia). Les valeurs sont lues au clavier, jamais
sur la ligne de commande — elles ne se retrouvent donc ni dans l'historique du
shell, ni dans la sortie du terminal.

Sans terminal interactif (service détaché, conteneur, `./start.sh`), rien n'est
demandé : un court état part dans le journal et l'application démarre comme
avant. `./run.sh setup` permet de refaire cette étape quand on veut.
"""
import getpass
import os
import sys
from pathlib import Path

from . import auth
from .env import DEFAULT_PATH, read

ENV_PATH = DEFAULT_PATH
EXAMPLE_PATH = DEFAULT_PATH.with_name(".env.example")
CARTESIA_KEYS_URL = "https://play.cartesia.ai/keys"
CARTESIA_VERSION = "2026-08-14"


def create_from_example(path=ENV_PATH, example=EXAMPLE_PATH) -> bool:
    """Copie le modèle en fichier de configuration. False s'il existe déjà."""
    path = Path(path)
    if path.exists():
        return False
    example = Path(example)
    body = (example.read_text(encoding="utf-8") if example.is_file()
            else "# Configuration du coach de langue.\n")
    path.write_text(body, encoding="utf-8")
    try:
        path.chmod(0o600)  # des secrets vont y être écrits
    except OSError:
        pass  # système de fichiers sans permissions POSIX (Windows)
    return True


def set_value(key: str, value: str, path=ENV_PATH) -> None:
    """Écrit `key=value` en remplaçant la ligne du modèle, même commentée.

    Un doublon actif plus bas l'emporterait à la lecture : il est commenté au
    passage, pour que la valeur écrite soit bien celle qui s'applique.
    """
    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    prefix = f"{key}="
    written = False
    out = []
    for line in lines:
        body = line.lstrip("# ").strip()
        if body.startswith(prefix):
            if not written:
                out.append(f"{key}={value}")
                written = True
            else:
                out.append(f"# {body}")
        else:
            out.append(line)
    if not written:
        if out and out[-1].strip():
            out.append("")
        out.append(f"{key}={value}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def ask_secret(question: str, getpass_fn=getpass.getpass) -> str:
    """Pose la question sans afficher la saisie. Une ligne vide laisse tel quel."""
    try:
        return (getpass_fn(f"{question} ") or "").strip()
    except (EOFError, KeyboardInterrupt):
        print(file=sys.stderr)
        return ""


def check_cartesia(key: str) -> str | None:
    """Interroge l'API avec la clé.

    `""` : la clé répond. `None` : impossible de vérifier ici (dépendances
    absentes, réseau coupé) — ce n'est pas un succès pour autant. Sinon, la
    raison du refus. La clé n'est jamais affichée, même en cas d'échec.
    """
    try:
        import httpx
    except ImportError:
        return None
    try:
        res = httpx.get("https://api.cartesia.ai/voices", timeout=20,
                        headers={"X-API-Key": key, "Cartesia-Version": CARTESIA_VERSION})
    except Exception:  # noqa: BLE001 — réseau coupé, proxy, DNS…
        return None
    return "" if res.status_code == 200 else f"l'API Cartesia a répondu {res.status_code}"


def status(path=ENV_PATH) -> dict:
    """Ce qui est déjà configuré, sans rien demander (pour le journal)."""
    values = read(path) if Path(path).is_file() else {}
    return {"password": bool((values.get("LC_PASSWORD_HASH") or "").strip()),
            "cartesia": bool((values.get("CARTESIA_API_KEY") or "").strip())}


def main(path=ENV_PATH, *, interactive=None, getpass_fn=getpass.getpass, echo=print) -> int:
    """Prépare la configuration. Renvoie 0 dans tous les cas d'usage normal."""
    created = create_from_example(path)
    if created:
        echo(f"fichier de configuration créé : {Path(path).name} "
             f"(copie de {EXAMPLE_PATH.name})")
    state = status(path)
    done = state["password"] and state["cartesia"]

    if interactive is None:
        interactive = sys.stdin.isatty() and sys.stdout.isatty()
    if done or not interactive:
        if not done:
            manque = []
            if not state["password"]:
                manque.append("mot de passe du site (./run.sh setup)")
            if not state["cartesia"]:
                manque.append(f"clé Cartesia ({CARTESIA_KEYS_URL})")
            echo("à configurer : " + " et ".join(manque))
        return 0

    echo("\n— Préparation du coach —")
    echo("Entrée vide = laisser pour plus tard.\n")

    if not state["password"]:
        password = ask_secret("Mot de passe du site (pour toi, taper ne s'affiche pas) :",
                              getpass_fn)
        if password:
            set_value("LC_PASSWORD_HASH", auth.make_hash(password), path)
            echo("  mot de passe enregistré (seul le hash est écrit).")
        else:
            echo("  laissé vide : « ./run.sh hash » le générera plus tard.")

    if not status(path)["cartesia"]:
        echo(f"\n  Clé Cartesia pour entendre la langue cible — elle se crée sur {CARTESIA_KEYS_URL}")
        echo("  (clé standard, de la forme sk_car_…) ; facultatif, Entrée pour passer.")
        key = ask_secret("Clé Cartesia :", getpass_fn)
        if key:
            problem = check_cartesia(key)
            if problem is None:
                echo("  clé enregistrée (non vérifiée ici : réseau ou dépendances absents).")
            elif problem:
                echo(f"  attention : {problem}. La clé est conservée, à revérifier plus tard.")
            else:
                echo("  clé vérifiée auprès de l'API.")
            set_value("CARTESIA_API_KEY", key, path)
        else:
            echo("  laissé vide : tout fonctionne sauf le son.")

    state = status(path)
    echo("\nConfiguration : "
         + f"mot de passe {'ok' if state['password'] else 'absent'}, "
         + f"voix {'ok' if state['cartesia'] else 'absente'}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
