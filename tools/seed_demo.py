"""Amorce un carnet de démonstration pour vérifier les pages à la main.

Usage : LC_DATA_DIR=... .venv/bin/python tools/seed_demo.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import db, notebook  # noqa: E402

state = notebook.new_notebook(
    "ja",
    {"name": "Alex", "objective": "parler avec une amie japonaise", "level": "A1",
     "cadence": "3 séances par semaine", "context": "mangas, sport",
     "audio": {"ecoute": True, "parle": True}},
    start="2026-10-01",
    resources=[{"id": "GUqFU5u7rLQ", "date": "2026-10-01",
                "title": "Japanese Listening Practice With A Story #1 | Family [Beginner Level 1]",
                "url": "https://www.youtube.com/watch?v=GUqFU5u7rLQ",
                "channel": "Japarrot!- Let's Learn Japanese", "duration": 381, "note": ""}],
)
with db.write() as conn:
    notebook.insert_version(conn, state)

notebook.apply_update({"session": {"id": "2026-10-02-seance", "date": "2026-10-02", "minutes": 42,
                                   "kind": "apprentissage", "summary": "Écoute d'un extrait, production écrite.",
                                   "evidence": "4 réponses sur 5 sans modèle.", "completed": True,
                                   "completion_evidence": "Variante réussie sans indice.",
                                   "errors": ["particule は omise puis corrigée"]}})
notebook.apply_update({"calibration": [{
    "id": "cal-2026-10-02", "date": "2026-10-02", "felt": "trop_facile",
    "observation": "quatre réponses justes sans hésitation, deux pauses seulement",
    "change": "production allongée (3 phrases) et moins d'indices au rappel",
    "carry": "la particule は à retester après une autre tâche"}]})
notebook.apply_update({"calibration": [{
    "id": "cal-2026-10-03", "date": "2026-10-03", "felt": "trop_dur",
    "observation": "extrait de 6 min trop rapide, deux écoutes insuffisantes",
    "change": "extrait réduit à 30 s et question globale d'abord"}]})
print("carnet de démonstration prêt")
