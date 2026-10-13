"""FastAPI app: password session guard, OAuth bootstrap, threads and coaching."""
import json
import os
import re
from pathlib import Path
from urllib.parse import unquote
from zoneinfo import ZoneInfo

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from . import (anki, auth, coach, db, gemini, languages, notebook, opencode, resources,
               settings, timer, tts)

STATIC = Path(__file__).parent / "static"
# The manifest is fetched without cookies, so it and its icons must be public.
PUBLIC = {"/login", "/static/manifest.json", "/static/icon-192.png", "/static/icon-512.png"}


class AuthGuard(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.url.path in PUBLIC:
            return await call_next(request)
        if auth.valid_session(request.cookies.get(auth.COOKIE_NAME)):
            return await call_next(request)
        if request.url.path.startswith("/api/"):
            return JSONResponse({"detail": "unauthenticated"}, status_code=401)
        return RedirectResponse("/login", status_code=302)


app = FastAPI()
app.add_middleware(AuthGuard)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.middleware("http")
async def revalidate_statics(request: Request, call_next):
    """No heuristic caching for html/js/css: a stale app.js on mobile can
    survive a deploy for hours. "no-cache" still caches, just revalidates."""
    resp = await call_next(request)
    if request.url.path.endswith((".html", ".js", ".css")) or request.url.path in ("/", "/progres"):
        resp.headers["Cache-Control"] = "no-cache"
    return resp


@app.get("/login")
def login_page():
    return FileResponse(STATIC / "login.html")


@app.post("/login")
def login(request: Request, body: dict):
    ip = request.client.host if request.client else "?"
    if auth.throttled(ip):
        return JSONResponse({"detail": "too many attempts"}, status_code=429)
    if not auth.configured():
        # Cause la plus fréquente d'un « mot de passe refusé » : rien à comparer.
        return JSONResponse(
            {"detail": "Aucun mot de passe configuré côté serveur : renseigner LC_PASSWORD_HASH "
                       "dans le fichier .env (la commande « ./run.sh hash » l'affiche), "
                       "sans le # en début de ligne."},
            status_code=503)
    ok = auth.check_password(body.get("password", ""))
    auth.record_attempt(ip, ok)
    if not ok:
        return JSONResponse({"detail": "wrong password"}, status_code=401)
    res = JSONResponse({"ok": True})
    res.set_cookie(
        auth.COOKIE_NAME,
        auth.make_session(),
        max_age=auth.SESSION_TTL,
        httponly=True,
        samesite="lax",
        secure=os.environ.get("LC_COOKIE_SECURE") == "1",
    )
    return res


@app.post("/logout")
def logout():
    res = JSONResponse({"ok": True})
    res.delete_cookie(auth.COOKIE_NAME)
    return res


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


@app.get("/oauth/login")
def oauth_login():
    return RedirectResponse(gemini.login_url())


@app.get("/oauth-callback")
def oauth_callback(code: str = "", state: str = ""):
    try:
        gemini.complete_login(code, state)
    except ValueError:
        return JSONResponse({"detail": "bad state"}, status_code=400)
    return RedirectResponse("/")


def _closed_timer_ids() -> set:
    state = notebook.load()
    return {s["timer_id"] for s in (state or {}).get("sessions", []) if s.get("timer_id")}


@app.get("/api/threads")
def threads():
    closed = _closed_timer_ids()
    return [{**t, "closed": bool(t.get("timer_id") and t["timer_id"] in closed)}
            for t in db.list_threads()]


@app.post("/api/threads")
def new_thread():
    return db.create_thread()


@app.get("/api/threads/{thread_id}")
def thread_view(thread_id: int):
    thread = db.get_thread(thread_id)
    if not thread:
        return JSONResponse({"detail": "fil inconnu"}, status_code=404)
    closed = thread.get("timer_id") in _closed_timer_ids() if thread.get("timer_id") else False
    return {
        **thread,
        "caps": _caps(thread),
        "closed": closed,
        "pending_request": db.pending_request(thread_id),
        "timer": timer.summary(thread["timer_id"]) if thread.get("timer_id") else None,
    }


def _caps(thread: dict) -> dict | None:
    return coach.session_caps(thread)


@app.post("/api/session")
def start_session(body: dict | None = None):
    caps = ({"ecoute": bool(body.get("ecoute")), "parle": bool(body.get("parle"))}
            if body is not None else None)
    thread, created = coach.start_session(caps)
    return {"id": thread["id"], "title": thread["title"], "created": created,
            "caps": _caps(thread)}


@app.get("/api/threads/{thread_id}/side")
def side(thread_id: int):
    thread = db.get_thread(thread_id)
    if not thread:
        return JSONResponse({"detail": "fil inconnu"}, status_code=404)
    if thread.get("kind") != "session":
        return JSONResponse({"detail": "réservé aux séances"}, status_code=400)
    return db.side_thread(thread_id)


@app.post("/api/threads/{thread_id}/note")
def note(thread_id: int, body: dict):
    """A note from the side thread lands as a visible event; the coach reads
    it on its next turn since wire contents replay every stored row."""
    thread = db.get_thread(thread_id)
    if not thread:
        return JSONResponse({"detail": "fil inconnu"}, status_code=404)
    if thread.get("kind") != "session":
        return JSONResponse({"detail": "réservé aux séances"}, status_code=400)
    if coach.session_closed(thread):
        return JSONResponse({"detail": "séance terminée"}, status_code=409)
    text = (body.get("text") or "").strip()
    if not text:
        return JSONResponse({"detail": "note vide"}, status_code=400)
    shown = text if len(text) <= 160 else text[:157] + "…"
    db.add_message(thread_id, "user", "", kind="event", label=f"📌 {shown}",
                   parts=[{"text": f"(Note transmise par {coach.learner_name()} depuis le fil de "
                                   f"questions : {text})"}])
    return {"ok": True}


@app.get("/api/threads/{thread_id}/messages")
def messages(thread_id: int):
    return [{k: m[k] for k in ("role", "kind", "text", "attachment", "label", "created_at")}
            for m in db.list_messages(thread_id)]


@app.post("/api/threads/{thread_id}/turn")
def turn(thread_id: int, body: dict):
    thread = db.get_thread(thread_id)
    if not thread:
        return JSONResponse({"detail": "fil inconnu"}, status_code=404)
    if coach.session_closed(thread):
        return JSONResponse({"detail": "séance terminée"}, status_code=409)
    if thread.get("kind") == "side":
        parent = db.get_thread(thread.get("parent_id") or 0)
        if parent and coach.session_closed(parent):
            return JSONResponse({"detail": "séance terminée"}, status_code=409)
    # Finish on a session l'apprenant never engaged with deletes every trace
    # instead of asking the coach for a recap.
    if (body.get("event") == "finish" and thread.get("kind") == "session"
            and not db.has_user_input(thread_id)):
        db.delete_thread(thread_id)
        return StreamingResponse(iter([json.dumps({"type": "discarded"}) + "\n"]),
                                 media_type="application/x-ndjson; charset=utf-8")
    if not gemini.has_token():
        return JSONResponse({"detail": "no model access: /oauth/login (gemini) or OPENCODE_API_KEY (opencode)"},
                            status_code=503)
    event = body.get("event", "message")
    text = (body.get("text") or "").strip()
    audio = (body.get("audio") or "").strip()
    # Ressenti de fin de séance : déclaré dans l'interface, il part tel quel dans
    # l'instruction de clôture (et devient le `felt` de l'auto-critique).
    felt = str(body.get("felt") or "").strip()
    comment = str(body.get("comment") or "").strip()[:500]
    if felt and felt not in notebook.FELT:
        return JSONResponse({"detail": "ressenti inconnu"}, status_code=400)
    if felt == "non_dit":
        felt = ""
    if event not in ("start", "finish", "message"):
        return JSONResponse({"detail": "événement inconnu"}, status_code=400)
    if event in ("start", "finish") and thread.get("kind") != "session":
        return JSONResponse({"detail": "réservé aux séances"}, status_code=400)
    if event == "message" and not text and not audio:
        return JSONResponse({"detail": "message vide"}, status_code=400)
    if audio:
        try:
            notebook.audio_path(notebook.audio_root(), audio)
        except ValueError:
            return JSONResponse({"detail": "audio invalide"}, status_code=400)
    if event == "start" and any(m["role"] == "model" for m in db.list_messages(thread_id)):
        event = "noop"  # opening already streamed once

    def stream():
        if event == "noop":
            yield json.dumps({"type": "done"}, ensure_ascii=False) + "\n"
            return
        try:
            for ev in coach.stream_events(thread, event, text=text, audio=audio,
                                          seconds=body.get("seconds"), felt=felt, comment=comment):
                yield json.dumps(ev, ensure_ascii=False) + "\n"
        except Exception as e:
            yield json.dumps({"type": "error", "message": str(e)}, ensure_ascii=False) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson; charset=utf-8")


def _voice_catalog(code: str) -> list[dict]:
    """Voix disponibles pour la langue du carnet. Liste vide si Cartesia n'est
    pas configuré, plutôt qu'une erreur dans les réglages."""
    if not code or not languages.has(code):
        return []
    try:
        return tts.list_voices(languages.get(code))
    except (tts.Unavailable, httpx.HTTPError):
        return []


@app.get("/api/languages")
def get_languages():
    """Ce que l'initialisation propose : langues, registres, niveaux."""
    return {"languages": languages.catalog()}


@app.get("/api/profile")
def get_profile():
    state = notebook.load()
    code = (state or {}).get("language")
    return {"onboarded": state is not None,
            "language": code,
            # L'interface s'en sert pour repérer le texte audible : la langue du
            # carnet décide, le paquet fournit le motif d'écriture.
            "script": languages.get(code).script if code else None,
            "profile": (state or {}).get("profile"),
            "deadline": (state or {}).get("target"),
            "languages": languages.catalog()}


@app.get("/onboarding")
def onboarding_page():
    return FileResponse(STATIC / "onboarding.html")


@app.post("/api/resource-search")
def resource_search(body: dict):
    """Vidéos candidates : une vraie recherche, sans clé API. Les candidats
    existent réellement (titre, chaîne, durée) ; l'apprenant décide lesquels
    entrent dans son carnet."""
    code = str(body.get("language") or "").strip() or ((notebook.load() or {}).get("language") or "")
    if not code:
        return JSONResponse({"detail": "langue requise"}, status_code=400)
    try:
        language = languages.get(code)
    except ValueError as e:
        return JSONResponse({"detail": str(e)}, status_code=400)
    level = str(body.get("level") or "").strip()
    try:
        return {"language": code, "level": level, "candidates": resources.search(language, level)}
    except resources.Unavailable as e:
        return JSONResponse({"detail": str(e)}, status_code=503)


def _selected_resources(body: dict) -> list[dict]:
    """Les vidéos cochées à l'initialisation, datées à l'enregistrement."""
    when = str(body.get("start") or coach.today())
    return [resources.entry(c, when) for c in (body.get("resources") or []) if isinstance(c, dict)]


@app.post("/api/onboarding")
def onboarding(body: dict):
    """Crée le carnet : langue, objectif, niveau, cadence, contexte, vidéos
    validées — une seule fois, ensuite `/api/profile` suffit."""
    if notebook.load() is not None:
        return JSONResponse({"detail": "un carnet existe déjà : voir /api/profile"}, status_code=409)
    try:
        state = notebook.new_notebook(str(body.get("language") or ""),
                                      body.get("profile") or {}, start=body.get("start"),
                                      resources=_selected_resources(body),
                                      target=str(body["deadline"]).strip() if body.get("deadline") else None)
        with db.write() as conn:
            notebook.insert_version(conn, state)
    except (ValueError, KeyError, TypeError) as e:
        return JSONResponse({"detail": str(e)}, status_code=400)
    return get_profile()


@app.post("/api/profile")
def set_profile(body: dict):
    """Modifie le profil en cours de route : objectif, cadence, registres visés,
    contexte, échéance facultative."""
    if notebook.load() is None:
        return JSONResponse({"detail": "initialisation à faire"}, status_code=404)
    patch = {}
    if isinstance(body.get("profile"), dict):
        patch["profile"] = body["profile"]
    if "deadline" in body:
        patch["target"] = str(body.get("deadline")).strip() or None
    if "next" in body:
        patch["next"] = str(body["next"]).strip()
    if not patch:
        return JSONResponse({"detail": "rien à mettre à jour"}, status_code=400)
    try:
        notebook.apply_update(patch)
    except (ValueError, KeyError, TypeError) as e:
        return JSONResponse({"detail": str(e)}, status_code=400)
    return get_profile()


@app.get("/api/settings")
def get_settings():
    catalogs = {"gemini": gemini.MODELS, "opencode": opencode.models()}
    current = settings.current_model()
    if current not in catalogs[settings.current_provider()]:
        catalogs[settings.current_provider()].append(current)
    code = (notebook.load() or {}).get("language") or ""
    return {"provider": settings.current_provider(), "model": current, "models": catalogs,
            "timezone": settings.timezone(), "language": code,
            "voice": settings.voice(code) if code else None}


@app.get("/api/voices")
def voices():
    code = (notebook.load() or {}).get("language")
    if not code:
        return JSONResponse({"detail": "aucune langue configurée"}, status_code=404)
    return {"language": code, "current": settings.voice(code), "voices": _voice_catalog(code)}


@app.post("/api/settings")
def set_settings(body: dict):
    provider = body.get("provider")
    model = str(body.get("model") or "").strip()
    zone = str(body.get("timezone") or "").strip()
    if provider is not None and provider not in settings.PROVIDERS:
        return JSONResponse({"detail": "provider inconnu"}, status_code=400)
    if model and not re.fullmatch(r"[\w.:-]{1,100}", model):
        return JSONResponse({"detail": "modèle invalide"}, status_code=400)
    if zone:
        try:
            ZoneInfo(zone)
        except (KeyError, ValueError):
            return JSONResponse({"detail": "fuseau inconnu"}, status_code=400)
    settings.save(provider=provider, model=model or None, timezone=zone or None)
    if "voice" in body:
        code = (notebook.load() or {}).get("language")
        if not code:
            return JSONResponse({"detail": "aucune langue configurée"}, status_code=400)
        settings.set_voice(code, str(body.get("voice") or "").strip() or None)
    return get_settings()


@app.post("/api/threads/{thread_id}/pause")
def pause(thread_id: int):
    thread = db.get_thread(thread_id)
    if not thread or not thread.get("timer_id"):
        return JSONResponse({"detail": "pas de chronomètre"}, status_code=404)
    try:
        timer.pause(thread["timer_id"], task=thread.get("title", ""))
    except ValueError as e:
        return JSONResponse({"detail": str(e)}, status_code=409)
    return timer.summary(thread["timer_id"])


@app.post("/api/threads/{thread_id}/resume")
def resume(thread_id: int):
    thread = db.get_thread(thread_id)
    if not thread or not thread.get("timer_id"):
        return JSONResponse({"detail": "pas de chronomètre"}, status_code=404)
    try:
        timer.resume(thread["timer_id"])
    except ValueError as e:
        return JSONResponse({"detail": str(e)}, status_code=409)
    return timer.summary(thread["timer_id"])


@app.get("/api/threads/{thread_id}/timer")
def timer_state(thread_id: int):
    thread = db.get_thread(thread_id)
    if not thread or not thread.get("timer_id"):
        return JSONResponse({"detail": "pas de chronomètre"}, status_code=404)
    return timer.summary(thread["timer_id"])


@app.post("/api/audio")
async def upload_audio(request: Request):
    mime = request.headers.get("X-Audio-Mime", "audio/webm")
    seconds = request.headers.get("X-Audio-Seconds")
    data = await request.body()
    try:
        rel = coach.store_audio(data, mime, float(seconds) if seconds else None)
    except ValueError as e:
        return JSONResponse({"detail": str(e)}, status_code=400)
    return {"path": rel}


@app.get("/api/audio/{path:path}")
def get_audio(path: str):
    try:
        full = notebook.audio_path(notebook.audio_root(), path)
    except ValueError:
        return JSONResponse({"detail": "audio invalide"}, status_code=400)
    if not full.is_file():
        return JSONResponse({"detail": "audio absent"}, status_code=404)
    return FileResponse(full)


@app.get("/api/tts")
def tts_clip(text: str = "", speed: str = "normal"):
    """GET so the browser plays it straight from <audio src>, which keeps
    playback inside the tap gesture on iOS."""
    try:
        rel = tts.clip(text, speed)
    except ValueError as e:
        return JSONResponse({"detail": str(e)}, status_code=400)
    except (tts.Unavailable, httpx.HTTPError) as e:
        return JSONResponse({"detail": f"voix indisponible : {e}"}, status_code=503)
    return FileResponse(notebook.audio_root() / rel, media_type="audio/mpeg",
                        headers={"Cache-Control": "private, max-age=604800"})


@app.get("/api/recordings")
def recordings():
    state = notebook.load()
    out = []
    for r in reversed((state or {}).get("recordings", [])):
        full = notebook.audio_path(notebook.audio_root(), r["path"])
        out.append({**r, "missing": not full.is_file()})
    return out


@app.get("/api/anki")
def anki_packages():
    state = notebook.load()
    return anki.package_list(state) if state else []


@app.get("/progres")
def progress_page():
    return FileResponse(STATIC / "progres.html")


@app.get("/api/progress")
def progress_report():
    state = notebook.load()
    if state is None:
        return JSONResponse({"detail": "aucun carnet"}, status_code=404)
    return notebook.report_data(state, notebook.day(coach.today()))


@app.get("/api/anki/{name}")
def anki_download(name: str):
    """Regenerated from the current notebook on every download."""
    state = notebook.load()
    if state is None:
        return JSONResponse({"detail": "aucun carnet"}, status_code=404)
    try:
        path, _count = anki.build(state, name)
    except ValueError as e:
        return JSONResponse({"detail": str(e)}, status_code=404)
    return FileResponse(path, filename=name)


@app.post("/api/recordings/import")
async def import_recording(request: Request):
    seconds = request.headers.get("X-Audio-Seconds")
    try:
        entry = coach.import_recording(
            await request.body(),
            unquote(request.headers.get("X-Audio-Name", "")),
            task=request.headers.get("X-Audio-Task", ""),
            mode=request.headers.get("X-Audio-Mode", ""),
            when=request.headers.get("X-Audio-Date") or coach.today(),
            note=unquote(request.headers.get("X-Audio-Note", "")),
            seconds=float(seconds) if seconds else None,
        )
    except ValueError as e:
        return JSONResponse({"detail": str(e)}, status_code=400)
    return entry


if __name__ == "__main__":
    uvicorn.run("app.main:app", host="127.0.0.1", port=int(os.environ.get("LC_PORT", "51121")))
