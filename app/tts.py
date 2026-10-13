"""Audio de référence : synthèse vocale Cartesia, mise en cache sur disque.

Un extrait est synthétisé une fois par (texte, voix, vitesse, langue) et relu
depuis `data/audio/tts/` ensuite : réécouter ne coûte plus rien. La langue et
la voix viennent du language pack et des réglages — aucune langue n'est codée
en dur ici.
"""
import hashlib
import json
import os
import re
import unicodedata

import httpx

from . import languages, notebook, settings

API = "https://api.cartesia.ai/tts/bytes"
VOICES_API = "https://api.cartesia.ai/voices"
VERSION = "2026-08-14"
SPEEDS = {"normal": 1.0, "lent": 0.6}
MAX_CHARS = 200


class Unavailable(Exception):
    """Cartesia n'est pas configuré ou a refusé la requête."""


def _key() -> str:
    key = os.environ.get("CARTESIA_API_KEY")
    if not key:
        raise Unavailable("CARTESIA_API_KEY absente")
    return key


def _headers() -> dict:
    return {"X-API-Key": _key(), "Cartesia-Version": VERSION}


def active_language() -> languages.Language:
    """La langue du carnet courant : c'est l'initialisation qui la fixe."""
    state = notebook.load()
    if state is None:
        raise ValueError("Aucun carnet : passer par l'initialisation.")
    return languages.get(state.get("language") or "")


def clean(text: str, language: languages.Language) -> str:
    text = " ".join(unicodedata.normalize("NFC", text or "").split())
    notebook.require(0 < len(text) <= MAX_CHARS, "Texte vide ou trop long.")
    notebook.require(bool(re.search(language.script, text)),
                     f"Texte en {language.name} attendu pour la synthèse.")
    return text


def list_voices(language: languages.Language) -> list[dict]:
    """Voix actives disponibles pour cette langue, pour le sélecteur de réglages."""
    res = httpx.get(VOICES_API, params={"language": language.tts_language},
                    headers=_headers(), timeout=30)
    if res.status_code != 200:
        raise Unavailable(f"Cartesia {res.status_code} : {res.text[:200]}")
    return [{"id": v["id"], "name": v.get("name", ""), "gender": v.get("gender", ""),
             "description": v.get("description", "")}
            for v in res.json().get("data", []) if v.get("status") == "active"]


def _resolved_voice(language: languages.Language) -> str:
    """Première voix active de la langue, mémorisée dans les réglages."""
    candidates = list_voices(language)
    if language.tts_voice_hint:
        preferred = [v for v in candidates if v["gender"] == language.tts_voice_hint]
        candidates = preferred or candidates
    if not candidates:
        raise Unavailable(f"Aucune voix {language.name} disponible sur ce compte Cartesia.")
    settings.set_voice(language.code, candidates[0]["id"])
    return candidates[0]["id"]


def voice(language: languages.Language) -> str:
    """Voix à utiliser : réglage du site, variable d'environnement, paquet, puis
    première voix de la langue résolue par l'API et mémorisée."""
    return (settings.voice(language.code) or os.environ.get("CARTESIA_VOICE_ID")
            or language.tts_voice or _resolved_voice(language))


def clip(text: str, speed: str, language: languages.Language | None = None) -> str:
    """Chemin relatif de l'extrait, synthétisé s'il n'est pas déjà en cache."""
    language = language or active_language()
    text = clean(text, language)
    notebook.require(speed in SPEEDS, "Vitesse inconnue.")
    voice_id = voice(language)
    key = f"{text}|{voice_id}|{speed}|{language.tts_language}"
    rel = f"tts/{hashlib.sha1(key.encode()).hexdigest()}.mp3"
    full = notebook.audio_root() / rel
    if full.is_file():
        return rel
    res = httpx.post(API, timeout=30, headers=_headers(), json={
        "model_id": "sonic-3.6",
        "transcript": text,
        "voice": voice_id,
        "language": language.tts_language,
        "output_format": {"container": "mp3", "sample_rate": 44100, "bit_rate": 128000},
        "generation_config": {"speed": SPEEDS[speed]},
    })
    if res.status_code != 200:
        raise Unavailable(f"Cartesia {res.status_code} : {res.text[:200]}")
    full.parent.mkdir(parents=True, exist_ok=True)
    tmp = full.with_suffix(".part")
    tmp.write_bytes(res.content)
    tmp.replace(full)
    with (full.parent / "index.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps({"file": full.name, "text": text, "voice": voice_id, "speed": speed,
                            "language": language.code, "at": notebook.stamp()},
                           ensure_ascii=False) + "\n")
    return rel
