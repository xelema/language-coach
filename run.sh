#!/usr/bin/env bash
# Lance le coach en avant-plan sur http://127.0.0.1:51121.
# Au premier lancement : crée le venv et installe les dépendances.
# Pour un service détaché : ./start.sh (log dans .run/app.log).
#
# Le port 51121 n'est pas un hasard : le redirect Google du login Gemini est
# épinglé dessus. Surchargeable avec LC_PORT (utile en test).
set -euo pipefail
cd "$(dirname "$0")"

# Windows (Git Bash) n'a pas de .venv/bin : l'interpréteur est dans Scripts/.
pick_python() {
  if [ -x ".venv/bin/python" ]; then echo ".venv/bin/python"; return; fi
  if [ -x ".venv/Scripts/python.exe" ]; then echo ".venv/Scripts/python.exe"; return; fi
  echo ""
}

PY="$(pick_python)"
# Un venv vide ou interrompu doit se réparer tout seul : on vérifie une
# dépendance clé, pas seulement l'existence du dossier.
if [ -z "$PY" ] || ! "$PY" -c "import fastapi, genanki" >/dev/null 2>&1; then
  [ -n "$PY" ] || { python3 -m venv .venv 2>/dev/null || python -m venv .venv; }
  PY="$(pick_python)"
  [ -n "$PY" ] || { echo "impossible de créer .venv (python3 ou python requis)" >&2; exit 1; }
  "$PY" -m pip install -q --upgrade pip >&2
  "$PY" -m pip install -q -r requirements.txt >&2
fi

PORT="${LC_PORT:-51121}"
echo "coach sur http://127.0.0.1:${PORT}" >&2
exec "$PY" -m uvicorn app.main:app --host 127.0.0.1 --port "$PORT"
