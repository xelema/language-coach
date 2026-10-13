"""Sonde : peut-on récupérer un vrai transcript (sous-titres auto) et un court
extrait audio d'une vidéo, sans clé API, depuis ce VPS ?"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import yt_dlp

VIDEO = sys.argv[1] if len(sys.argv) > 1 else "GUqFU5u7rLQ"  # Japarrot! #1 (débutant)

tmp = Path(tempfile.mkdtemp())

print("== sous-titres disponibles ==")
try:
    with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True,
                           "listsubtitles": True}) as ydl:
        ydl.download([f"https://www.youtube.com/watch?v={VIDEO}"])
except Exception as exc:  # noqa: BLE001
    print("ECHEC list:", type(exc).__name__, str(exc)[:300])

print("\n== téléchargement des sous-titres ==")
opts = {"quiet": True, "no_warnings": True, "skip_download": True,
        "writeautomaticsub": True, "writesubtitles": True,
        "subtitleslangs": ["ja", "en", "fr", "ja-orig", "ko"],
        "subtitlesformat": "json3/vtt/best",
        "outtmpl": str(tmp / "%(id)s.%(ext)s")}
try:
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={VIDEO}", download=True)
    print("titre:", info.get("title"), "| durée:", info.get("duration"), "s")
except Exception as exc:  # noqa: BLE001
    print("ECHEC subs:", type(exc).__name__, str(exc)[:400])

files = sorted(p for p in tmp.iterdir())
print("fichiers:", [p.name for p in files])
for p in files:
    if p.suffix in (".json3", ".vtt", ".srt"):
        head = p.read_text(encoding="utf-8", errors="replace")[:600]
        print(f"--- {p.name} ({p.stat().st_size} o) ---\n{head}\n")

print("== ffmpeg ==")
for cmd in (["ffmpeg", "-version"], ["ffprobe", "-version"]):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        print(cmd[0], out.stdout.splitlines()[0] if out.stdout else out.stderr[:120])
    except FileNotFoundError:
        print(cmd[0], "absent")
