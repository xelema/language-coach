#!/usr/bin/env bash
# Lance le projet en avant-plan. En prod lab: setsid nohup ./run.sh > .run/app.log 2>&1 &
set -euo pipefail
cd "$(dirname "$0")"
echo "rien à lancer pour l'instant — édite run.sh" >&2
