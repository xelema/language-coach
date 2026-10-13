"""Paquet de l'application.

Le `.env` est chargé ici, à l'import du paquet : ainsi toutes les façons de
lancer l'application (`./run.sh`, `python -m app.main`, `uvicorn app.main:app`)
le prennent en compte, sans que personne ait à exporter les variables à la main.
"""
from .env import load_env

load_env()
