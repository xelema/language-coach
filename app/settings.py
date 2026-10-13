"""Réglages du site (data/settings.json, qui survit aux redéploiements).

Fournisseur et modèle du coach, voix de synthèse choisie par langue. Ordre de
priorité : choix dans l'interface > variable d'environnement > défaut du paquet
de langue.
"""
import json
import os

from .auth import data_dir

PROVIDERS = ("gemini", "opencode")
DEFAULT_MODEL = {"gemini": "gemini-3.8-flash-tiered", "opencode": "deepseek-v4.1-flash"}


def _file():
    return data_dir() / "settings.json"


def load() -> dict:
    try:
        return json.loads(_file().read_text())
    except (OSError, ValueError):
        return {}


def _store(state: dict) -> None:
    _file().write_text(json.dumps(state, ensure_ascii=False))


def current_provider() -> str:
    p = load().get("provider") or os.environ.get("LC_PROVIDER") or "gemini"
    return p if p in PROVIDERS else "gemini"


def current_model(provider: str | None = None) -> str:
    p = provider if provider in DEFAULT_MODEL else current_provider()
    return (load().get("models", {}).get(p)
            or os.environ.get("LC_MODEL") or DEFAULT_MODEL[p])


def timezone() -> str:
    """Fuseau utilisé pour les dates et les heures locales (réglage, sinon env)."""
    return load().get("timezone") or os.environ.get("LC_TIMEZONE") or "Europe/Paris"


def save(provider: str | None = None, model: str | None = None, timezone: str | None = None) -> None:
    state = load()
    if provider in PROVIDERS:
        state["provider"] = provider
    if model:
        # The model pick is kept per provider, so switching back restores it.
        state.setdefault("models", {})[state.get("provider") or current_provider()] = model
    if timezone:
        state["timezone"] = timezone
    _store(state)


def voice(language_code: str) -> str | None:
    """Voix de synthèse choisie pour cette langue, None si aucune."""
    return (load().get("voices") or {}).get(language_code)


def set_voice(language_code: str, voice_id: str | None) -> None:
    state = load()
    voices = state.setdefault("voices", {})
    if voice_id:
        voices[language_code] = voice_id
    else:
        voices.pop(language_code, None)
    _store(state)
