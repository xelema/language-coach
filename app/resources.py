"""Recherche de matériel d'écoute réel : des vidéos qui existent, sans clé API.

La recherche est une vraie requête, donc chaque candidat porte un titre, une
chaîne et une durée véritables — rien n'est inventé. L'apprenant les valide un
par un à l'initialisation, et seuls ceux qu'il garde entrent dans le carnet ;
le coach s'appuie ensuite dessus sans jamais fabriquer d'extrait ni de corrigé.

L'extraction YouTube n'est pas garantie : un serveur sans cookies se fait
refuser (« sign in to confirm you're not a bot »). Rien ici n'en dépend — sans
yt-dlp ou sans accès, la recherche échoue proprement et le reste de
l'application fonctionne.
"""
import re

from . import languages

# Ce qui rend une requête adaptée au niveau déjà connu.
QUERY_SUFFIX = {
    "A0": "débutant lent très simple",
    "A1.0": "débutant lent",
    "A1": "débutant lent",
    "A2": "niveau intermédiaire sous-titres",
    "B1": "conversation naturelle",
    "B2": "débat naturel débit normal",
}


class Unavailable(Exception):
    """Recherche impossible : yt-dlp absent, ou YouTube a refusé."""


def available() -> bool:
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        return False
    return True


def _search(query: str, limit: int) -> list[dict]:
    import yt_dlp

    options = {"quiet": True, "no_warnings": True, "skip_download": True,
               "extract_flat": True, "socket_timeout": 20, "cachedir": False}
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
    found = []
    for entry in info.get("entries") or []:
        if not entry or not entry.get("id"):
            continue
        found.append({
            "id": entry["id"],
            "title": (entry.get("title") or "").strip(),
            "channel": (entry.get("channel") or entry.get("uploader") or "").strip(),
            "duration": entry.get("duration"),
            "url": entry.get("url") or f"https://www.youtube.com/watch?v={entry['id']}",
            "views": entry.get("view_count"),
        })
    return found


def search(language, level: str = "", limit: int = 6) -> list[dict]:
    """Candidats réels pour cette langue et ce niveau, dédupliqués."""
    if not isinstance(language, languages.Language):
        raise Unavailable("Langue inconnue.")
    if not available():
        raise Unavailable("yt-dlp n'est pas installé : la recherche de vidéos est indisponible.")
    suffix = QUERY_SUFFIX.get(level or "", "")
    queries = language.listening_queries or (f"{language.name} compréhension orale",)
    seen, found, errors = set(), [], []
    for query in queries[:2]:
        try:
            results = _search(f"{query} {suffix}".strip(), limit)
        except Exception as exc:  # noqa: BLE001 — toute erreur d'extraction reste non bloquante
            errors.append(f"{type(exc).__name__}: {exc}"[:200])
            continue
        for item in results:
            if item["id"] in seen or not item["title"]:
                continue
            seen.add(item["id"])
            found.append(item)
    if not found:
        raise Unavailable("Recherche impossible : " + (" ; ".join(errors) or "aucun résultat"))
    return found[:limit]


def entry(candidate: dict, when: str) -> dict:
    """Une vidéo validée par l'apprenant, telle qu'elle est enregistrée."""
    title = str(candidate.get("title") or "").strip()
    url = str(candidate.get("url") or "").strip()
    if not title or not re.match(r"^https?://", url):
        raise ValueError("Vidéo invalide : titre et URL attendus.")
    duration = candidate.get("duration")
    return {"id": str(candidate.get("id") or url)[:80], "date": when, "title": title[:300],
            "url": url[:500], "channel": str(candidate.get("channel") or "")[:200],
            "duration": int(duration) if isinstance(duration, (int, float)) else None,
            "note": str(candidate.get("note") or "")[:500]}
