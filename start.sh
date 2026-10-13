#!/usr/bin/env bash
# Lance le projet détaché de ce shell : ./start.sh (log dans .run/app.log).
# Indispensable pour les outils Hermes: une commande foreground contenant
# setsid/nohup est refusée, un wrapper ne l'est pas.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p .run
setsid nohup ./run.sh > .run/app.log 2>&1 < /dev/null &
echo "lancé derrière ce shell (log: .run/app.log)"
