"""Sonde : yt-dlp peut-il servir de recherche vidéo sans clé API, depuis ce VPS ?"""
import json
import sys

import yt_dlp

QUERIES = [
    "japonais débutant compréhension orale dialogue lent",
    "Nihongo listening practice beginner slow conversation",
    "coréen débutant dialogue lent écoute",
]


def search(query, n=5):
    opts = {"quiet": True, "no_warnings": True, "skip_download": True,
            "extract_flat": True, "socket_timeout": 20, "cachedir": False}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"ytsearch{n}:{query}", download=False)
    out = []
    for e in info.get("entries") or []:
        out.append({"id": e.get("id"), "title": e.get("title"),
                    "channel": e.get("channel") or e.get("uploader"),
                    "duration": e.get("duration"),
                    "live": e.get("live_status"), "views": e.get("view_count")})
    return out


for q in QUERIES:
    print(f"### {q}")
    try:
        for r in search(q):
            print(json.dumps(r, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001
        print("ECHEC:", type(exc).__name__, str(exc)[:300])
    print()
