#!/usr/bin/env bash
# Lance le coach en avant-plan sur http://localhost:51121.
#   ./run.sh          démarre le serveur (installe les dépendances au besoin,
#                     crée le fichier de configuration et demande ce qui manque)
#   ./run.sh setup    repose les questions de configuration, sans démarrer
#   ./run.sh hash     affiche la ligne LC_PASSWORD_HASH à coller dans .env
# Pour un service détaché : ./start.sh (log dans .run/app.log).
#
# Le port 51121 n'est pas un hasard : le redirect Google du login Gemini est
# épinglé dessus. Le `.env` posé à côté de ce script est lu par l'application
# elle-même (aucune variable à exporter à la main).
set -euo pipefail
cd "$(dirname "$0")"

# Windows (Git Bash) n'a pas de .venv/bin : l'interpréteur est dans Scripts/.
pick_python() {
  if [ -x ".venv/bin/python" ]; then echo ".venv/bin/python"; return; fi
  if [ -x ".venv/Scripts/python.exe" ]; then echo ".venv/Scripts/python.exe"; return; fi
  echo ""
}

PY="$(pick_python)"
if [ -z "$PY" ]; then
  python3 -m venv .venv 2>/dev/null || python -m venv .venv
  PY="$(pick_python)"
  [ -n "$PY" ] || { echo "impossible de créer .venv (python3 ou python requis)" >&2; exit 1; }
fi

# `hash` est indépendant des dépendances (le module n'utilise que la
# bibliothèque standard) : on peut générer le mot de passe avant tout install.
if [ "${1:-}" = "hash" ]; then
  exec "$PY" -m app.auth "${2:-}"
fi

# `setup` : reposer les questions de configuration et s'arrêter là.
if [ "${1:-}" = "setup" ]; then
  exec "$PY" -m app.setup
fi

# Un venv vide ou interrompu doit se réparer tout seul : on vérifie une
# dépendance clé, pas seulement l'existence du dossier.
if ! "$PY" -c "import fastapi, genanki" >/dev/null 2>&1; then
  "$PY" -m pip install -q --upgrade pip >&2
  "$PY" -m pip install -q -r requirements.txt >&2
fi

# Fichier de configuration : créé au premier lancement, complété si besoin
# (mot de passe du site, clé Cartesia). Sans terminal interactif, il ne pose
# aucune question : c'est le lancement en service qui passe par là.
"$PY" -m app.setup 2>&1 || true

# Prévenir avant d'ouvrir le navigateur, plutôt que de laisser un 401
# incompréhensible : on interroge le même chargeur de .env que l'application.
"$PY" - <<'PY' || true
from app.env import load_env
import os
import sys

load_env()
if not (os.environ.get("LC_PASSWORD_HASH") or "").strip():
    print("attention : aucun mot de passe configuré, la page de connexion refusera tout le monde.\n"
          "  lance « ./run.sh setup » pour le saisir, ou « ./run.sh hash » pour obtenir la ligne "
          "à coller dans le fichier .env",
          file=sys.stderr)
PY

PORT="${LC_PORT:-51121}"
# « localhost » et pas 127.0.0.1 : le retour de Google est épinglé sur
# localhost:51121, donc la session doit vivre sur ce nom d'hôte là.
echo "coach sur http://localhost:${PORT}" >&2
exec "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT"
