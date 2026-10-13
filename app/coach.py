"""Coach session loop: prompt assembly, tools, automatic timer, recordings.

A session is a thread with kind='session' and a timer_id. The coach prompt is
reassembled on every request from coach/*.md plus the live status, so saves and
day changes are always reflected without a model round trip. Tool calls run
in-process inside the streaming loop; the model turn is stored verbatim
(thoughtSignature included) and echoed back so function calling keeps working.
"""
import base64
import hashlib
import json
import queue
import re
import threading
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import anki, db, gemini, languages, notebook, prompts, settings, timer

# Les gabarits de coach/ : protocole de séance, niveaux et calibrage, ressources.
PROMPT_FILES = ("coach.md", "niveaux.md", "ressources.md")
DEFAULT_ZONE = "Europe/Paris"


def zone() -> ZoneInfo:
    """Fuseau des dates montrées au coach (réglage du site, sinon variable
    d'environnement, sinon Europe/Paris)."""
    try:
        return ZoneInfo(settings.timezone())
    except (KeyError, ValueError):
        return ZoneInfo(DEFAULT_ZONE)

TASKS = ("presentation", "journee", "film", "lecture", "conversation")
MODES = ("spontane", "lecture", "entraine")
MAX_AUDIO_BYTES = 8 * 1024 * 1024
MAX_AUDIO_SECONDS = 300
MAX_IMPORT_BYTES = 200 * 1024 * 1024

# Magic-byte checks per extension, ported from korean-learn/coach.py import_audio.
AUDIO_MAGIC = {
    ".wav": lambda h: h[:4] == b"RIFF" and h[8:12] == b"WAVE",
    ".mp3": lambda h: h[:3] == b"ID3" or (len(h) > 1 and h[0] == 255 and h[1] & 224 == 224),
    ".m4a": lambda h: h[4:8] == b"ftyp",
    ".ogg": lambda h: h[:4] == b"OggS",
    ".webm": lambda h: h[:4] == b"\x1aE\xdf\xa3",
    ".flac": lambda h: h[:4] == b"fLaC",
}
TASK_MARK = re.compile(r"\[tâche\s*:\s*([^\]]{1,80})\]")

# Field specs enforced by notebook.validate() : the model never sees them
# otherwise and has to guess names by trial and error.
_SESSION_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string", "description": "Unique et stable, ex. 2026-09-08-diagnostic."},
        "date": {"type": "string", "description": "AAAA-MM-JJ, date réelle."},
        "kind": {"type": "string",
                 "enum": ["diagnostic", "apprentissage", "consolidation", "bilan", "partielle"]},
        "summary": {"type": "string", "description": "Récapitulatif de la séance."},
        "evidence": {"type": "string", "description": "Preuves : exercices, réponses, mesures."},
        "minutes": {"type": "integer",
                    "description": "À omettre : rempli par le chrono. Seulement pour une durée "
                                   "déclarée différente du mesuré (provenance dans evidence)."},
        "completed": {"type": "boolean"},
        "completion_evidence": {"type": "string", "description": "Exigé quand completed est vrai."},
        "errors": {"type": "array", "items": {"type": "string"}},
        "time_confirmation": {"type": "string",
                              "description": "Exigé si une période mesurée dépasse 20 min."},
    },
    "required": ["id", "date", "kind", "summary", "evidence", "completed"],
}

def _card_schema(language) -> dict:
    """Le registre d'une carte vient du paquet de langue : seuls ceux de la
    langue enseignée sont acceptés, le modèle ne peut pas en inventer."""
    return {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "Unique et stable."},
            "prompt": {"type": "string",
                       "description": "Recto : langue maternelle ou intention, sans la réponse."},
            "answer": {"type": "string", "description": f"Verso : {language.name}."},
            "source": {"type": "string", "description": "Origine ou explication courte."},
            "register": {"type": "string", "enum": list(language.register_ids)},
            "skill": {"type": "string", "enum": ["ecoute", "oral", "ecrit", "registre"]},
            "introduced": {"type": "string", "description": "AAAA-MM-JJ, date réelle d'introduction."},
        },
        "required": ["id", "prompt", "answer", "source", "register", "skill", "introduced"],
    }


_CALIBRATION_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string", "description": "Unique et stable."},
        "date": {"type": "string", "description": "AAAA-MM-JJ."},
        "felt": {"type": "string", "enum": list(notebook.FELT),
                 "description": "Ressenti déclaré par l'apprenant à la clôture."},
        "observation": {"type": "string",
                        "description": "Ce que les réponses, les temps et les erreurs montrent réellement."},
        "change": {"type": "string",
                   "description": "Le seul réglage appliqué à la séance suivante (un cran maximum)."},
        "carry": {"type": "string", "description": "Ce qui reste à surveiller."},
        "applied": {"type": "boolean", "description": "Le réglage a-t-il déjà été appliqué ?"},
    },
    "required": ["id", "date", "felt", "observation", "change"],
}

_REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "card": {"type": "string", "description": "id d'une carte existante."},
        "date": {"type": "string", "description": "AAAA-MM-JJ."},
        "rating": {"type": "string", "enum": ["echec", "aide", "difficile", "reussi"]},
    },
    "required": ["id", "card", "date", "rating"],
}

_CHECKPOINT_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "date": {"type": "string", "description": "AAAA-MM-JJ."},
        "scores": {"type": "object",
                   "description": "Les quatre compétences, entier 0-4 ou null si non évaluée.",
                   "properties": {s: {"type": "integer", "nullable": True}
                                  for s in ("ecoute", "oral", "ecrit", "registre")},
                   "required": ["ecoute", "oral", "ecrit", "registre"]},
        "independent": {"type": "boolean"},
        "unseen": {"type": "boolean"},
        "audio_assessed": {"type": "boolean"},
        "provisional": {"type": "boolean"},
        "evidence": {"type": "object", "description": "Preuve par compétence notée."},
    },
    "required": ["id", "date", "scores", "independent", "unseen", "audio_assessed", "evidence"],
}

_RECORDING_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "date": {"type": "string", "description": "AAAA-MM-JJ."},
        "task": {"type": "string", "enum": list(TASKS)},
        "mode": {"type": "string", "enum": list(MODES)},
        "path": {"type": "string", "description": "Chemin relatif sous le dossier audio."},
        "note": {"type": "string"},
        "seconds": {"type": "number", "nullable": True},
        "sha256": {"type": "string"},
    },
    "required": ["id", "date", "task", "mode", "path", "note", "seconds"],
}

CHAT_FALLBACK = ("Tu es un assistant utile. Réponds en français, sobre et précis.")


def coach_tools(language) -> list[dict]:
    """Les quatre outils du coach. Leur vocabulaire est neutre (ils servent aussi
    au fil de conversation) : le nom de l'apprenant vit dans le prompt système,
    jamais dans les schémas."""
    return [
        {
            "name": "save_progress",
            "description": (
                "Enregistre un patch dans le carnet de progression. Clés permises : "
                "session, cards, reviews, checkpoint, calibration, next, resume, prep, "
                "recordings. En fin de séance, passe 'session' : le chronomètre est "
                "arrêté et timer_id/timing/minutes sont remplis automatiquement — "
                "n'écris 'minutes' que pour une durée déclarée différente du mesuré "
                "(provenance dans evidence). 'calibration' porte l'auto-critique de la "
                "séance et le réglage de la suivante. Renvoie le statut frais, ou "
                "l'erreur de validation à corriger avant de retenter."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "session": _SESSION_SCHEMA,
                    "cards": {"type": "array", "items": _card_schema(language)},
                    "reviews": {"type": "array", "items": _REVIEW_SCHEMA},
                    "checkpoint": _CHECKPOINT_SCHEMA,
                    "calibration": {"type": "array", "items": _CALIBRATION_SCHEMA},
                    "recordings": {"type": "array", "items": _RECORDING_SCHEMA},
                    "next": {"type": "string"},
                    "resume": {"type": "string", "nullable": True},
                    "prep": {"type": "string", "nullable": True},
                },
            },
        },
        {
            "name": "request_recording",
            "description": (
                "Demande une prise audio à l'apprenant : une carte s'affiche dans le "
                "fil et sa prochaine prise vocale y est rattachée, écoutée réellement "
                "et archivée dans le carnet. instructions = la consigne lue par "
                "l'apprenant."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "task": {"type": "string", "enum": list(TASKS)},
                    "mode": {"type": "string", "enum": list(MODES)},
                    "max_seconds": {"type": "integer"},
                    "instructions": {"type": "string"},
                },
                "required": ["task", "mode", "instructions"],
            },
        },
        {
            "name": "hear_recording",
            "description": (
                "Réécoute une prise archivée du carnet : l'audio t'est joint "
                "réellement à la réponse de l'outil (comparaison entre prises, relecture "
                "d'une prise précise). id = l'identifiant de la prise, listé dans "
                "« Prises archivées » du statut."
            ),
            "parameters": {
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
            },
        },
        {
            "name": "set_channels",
            "description": (
                "Met à jour les capacités audio de l'apprenant pour cette séance quand "
                "il annonce un changement (« finalement je peux parler », « plus moyen "
                "d'écouter »). ecoute = il peut entendre du son (texte cliquable, "
                "extraits) ; parle = il peut enregistrer des vocaux. Remplace les "
                "valeurs déclarées à l'ouverture ; adapte les exercices en conséquence."
            ),
            "parameters": {
                "type": "object",
                "properties": {"ecoute": {"type": "boolean"}, "parle": {"type": "boolean"}},
                "required": ["ecoute", "parle"],
            },
        },
    ]


def learner_name(state: dict | None = None) -> str:
    """Nom de l'apprenant, sinon une formule neutre : aucun prompt ne dépend
    d'une personne en particulier."""
    profile = (state if state is not None else notebook.load() or {}).get("profile") or {}
    return (profile.get("name") or "").strip() or "l'apprenant"


def chat_system(language) -> str:
    return (f"Tu es un coach de {language.name} utile, calme et précis, pour un "
            "apprenant francophone. Réponds en français, sans remplissage.")


def side_system(learner: str) -> str:
    return (f"Tu es le fil de questions à côté de la séance de {learner}. Réponds en "
            "français, court et précis. Tu vois le fil de la séance en lecture seule : "
            "tu n'écris jamais dans le carnet, tu ne lances pas d'exercice et tu ne "
            "déroules pas la séance. Si la solution de l'exercice en cours est "
            "demandée, donne un indice, jamais la réponse.")


# How much of the lesson the side thread sees.
SIDE_CONTEXT = 15


def kickoff(learner: str) -> str:
    return (f"(Séance lancée par {learner}. Tu as le statut complet ci-dessus : ouvre la "
            "séance, signale les absences depuis la dernière fois si besoin, annonce la "
            "mission et le premier défi. Une interaction à la fois.)")


def finish(learner: str) -> str:
    return (f"({learner.capitalize()} a demandé de terminer la séance. Fais le récap — "
            "acquis observé, priorité suivante, premier défi de la prochaine séance, "
            "cartes réellement travaillées, ressenti demandé et réglage retenu — puis "
            "appelle save_progress avec la session et l'auto-critique dans "
            "'calibration'.)")


def today() -> str:
    return datetime.now(zone()).date().isoformat()


def prompt_values(state: dict) -> dict:
    """Le contexte des gabarits : langue, profil, ressources, notes de langue.
    Aucune valeur ne suppose une personne ni une langue particulière."""
    language = languages.get((state or {}).get("language") or "")
    profile = (state or {}).get("profile") or {}
    deadline = (state or {}).get("target")
    return {
        "apprenant": learner_name(state),
        "langue": language.name,
        "langue_native": language.native_name,
        "langue_code": language.code,
        "objectif": profile.get("objective") or "(non précisé)",
        "niveau_declare": profile.get("level") or "(non précisé)",
        "niveau_verifie": profile.get("level_verified") or "pas encore vérifié (diagnostic à faire)",
        "niveaux_possibles": ", ".join(f"{lv.code} — {lv.label}" for lv in language.levels),
        "cadence": profile.get("cadence") or "libre",
        "contexte": profile.get("context") or "(rien de particulier)",
        "echeance": (f"{deadline} (l'apprenant en a donné une : la garder en vue sans s'y sacrifier)"
                     if deadline else "aucune échéance fixée, n'en impose pas"),
        "registres": ", ".join(f"{r.id} — {r.label}" for r in language.registers),
        "registres_defaut": language.default_register,
        "registres_vises": ", ".join(profile.get("registers") or list(language.register_ids)),
        "notes_langue": "\n".join(f"- {note}" for note in language.coaching_notes) or "- (aucune note de langue)",
        "ressources": "\n".join(f"- {res['name']} : {res['url']} ({res['note']})"
                                for res in language.resources) or "- (aucune ressource déclarée)",
        "ime_windows": language.ime.get("windows", ""),
        "ime_android": language.ime.get("android", ""),
        "ime_note": language.ime.get("note", ""),
    }


def system_prompt(thread: dict) -> str:
    state = notebook.load()
    if state is None:
        return (prompts.load(PROMPT_FILES, {})
                + "\n\n## État au moment de ce message\n\n"
                + "Carnet absent : l'initialisation n'a pas encore été faite.")
    values = {**prompt_values(state), "date": today()}
    dynamic = [f"## État au moment de ce message\n\nDate : {today()} ({settings.timezone()}).",
               "Statut du carnet :\n```json\n"
               + json.dumps(notebook.status(state, notebook.day(today())), ensure_ascii=False)
               + "\n```",
               "Préparation écrite à la fin de la dernière séance :\n"
               + (state.get("prep") or "(aucune — construis-la à partir de la prochaine action "
                                       "et du niveau vérifié)")]
    if state.get("recordings"):
        lines = [f"- {r['id']} · {r['date']} · {r['task']}/{r['mode']}"
                 + (f" · {r['seconds']:.0f} s" if r.get("seconds") else "")
                 + (f" · {r['note']}" if r.get("note") else "")
                 for r in state["recordings"]]
        dynamic.append("Prises archivées (réécoute via hear_recording) :\n" + "\n".join(lines))
    caps = session_caps(thread)
    if caps is not None:
        dynamic.append(
            "Capacités audio déclarées pour cette séance : "
            f"écoute {'possible' if caps['ecoute'] else 'IMPOSSIBLE'}, "
            f"parole {'possible' if caps['parle'] else 'IMPOSSIBLE'}. Respecte-les ; "
            "si l'apprenant annonce un changement, appelle set_channels.")
    if thread.get("timer_id"):
        summary = timer.summary(thread["timer_id"])
        if summary:
            chrono = (f"Chronomètre de cette séance : {summary['state']}, "
                      f"{summary['elapsed_minutes']:.0f} min écoulées "
                      f"(session {summary['session_minutes']:.0f}, pauses {summary['pause_minutes']:.0f}).")
            if summary["needs_confirmation"]:
                chrono += (" Une période dépasse 20 min : la durée devra être confirmée par "
                           "l'apprenant (champ time_confirmation).")
            dynamic.append(chrono)
    return "\n\n".join([prompts.load(PROMPT_FILES, values), "\n\n".join(dynamic)])


def side_prompt(thread: dict) -> str:
    """System prompt of a side thread: the lesson tail and the pending
    exercise, read-only. Rebuilt per request like the coach prompt."""
    main = db.get_thread(thread.get("parent_id") or 0)
    learner = learner_name()
    blocks = [side_system(learner)]
    if main:
        lines, task = [], ""
        for m in db.list_messages(main["id"]):
            if m["role"] == "model" and m["parts"]:
                for p in json.loads(m["parts"]):
                    if p.get("text") and not p.get("thought"):
                        found = TASK_MARK.findall(p["text"])
                        if found:
                            task = found[-1].strip()
            if m["kind"] == "tool":
                lines.append("⚙ " + (m["label"] or ""))
            elif m["kind"] == "event":
                if m["label"]:
                    lines.append("· " + m["label"])
            else:
                who = learner if m["role"] == "user" else "Coach"
                body = m["text"] or ("[vocal]" if m["attachment"] else "")
                if body:
                    lines.append(f"{who} : {body[:400]}")
        if lines:
            blocks.append("Fil de la séance (lecture seule, plus récent en bas) :\n"
                          + "\n".join(lines[-SIDE_CONTEXT:]))
        pending = []
        if task:
            pending.append(f"exercice en cours : {task}")
        req = db.pending_request(main["id"])
        if req:
            pending.append(f"enregistrement demandé : {req['task']} ({req['mode']}) — {req['instructions']}")
        if pending:
            blocks.append(f"En attente de {learner} : " + " ; ".join(pending))
    return "\n\n".join(blocks)


def meta_line(thread: dict, *, returned_after_s: float = 0.0, extra: str = "") -> str:
    bits = []
    if thread.get("timer_id"):
        summary = timer.summary(thread["timer_id"])
        if summary:
            bits.append(f"{summary['elapsed_minutes']:.0f} min écoulées")
            bits.append("chrono arrêté" if summary["stopped"]
                        else "en pause" if summary["state"] == "pause" else f"période {summary['state']}")
    if returned_after_s > timer.LONG_PERIOD_S:
        bits.append(f"retour après {returned_after_s / 60:.0f} min sans signaler : "
                    "demande-lui s'il travaillait ou était en pause avant de qualifier la durée")
    if extra:
        bits.append(extra)
    return "[méta · " + " · ".join(bits) + "]"


def wire_contents(thread_id: int) -> list[dict]:
    """Rebuilds the Gemini contents from stored rows, verbatim parts first."""
    contents = []
    for m in db.list_messages(thread_id):
        parts = json.loads(m["parts"]) if m["parts"] else [{"text": m["text"]}]
        if contents and contents[-1]["role"] == m["role"]:
            contents[-1]["parts"].extend(parts)
        else:
            contents.append({"role": m["role"], "parts": list(parts)})
    return contents


def extract_task(text: str) -> str:
    """The coach names the awaited task with a trailing [tâche: …] marker."""
    marks = TASK_MARK.findall(text)
    return marks[-1].strip() if marks else ""


def strip_marks(text: str) -> str:
    return TASK_MARK.sub("", text).rstrip()


def session_caps(thread: dict) -> dict | None:
    """Audio channels declared for the session, None when never declared.
    Accepts the stored JSON or an in-memory dict (e.g. create_thread's row)."""
    caps = thread.get("caps")
    if caps and not isinstance(caps, dict):
        try:
            caps = json.loads(caps)
        except (TypeError, json.JSONDecodeError):
            return None
    return caps if isinstance(caps, dict) and "ecoute" in caps and "parle" in caps else None


def session_closed(thread: dict) -> bool:
    """Closed once a session row references this timer (timer stopped + saved)."""
    if thread.get("kind") != "session" or not thread.get("timer_id"):
        return False
    state = notebook.load()
    if state is None:
        return False
    return any(s.get("timer_id") == thread["timer_id"] for s in state["sessions"])


def open_session_thread() -> dict | None:
    with db.connect() as conn:
        row = conn.execute(
            "SELECT t.* FROM threads t JOIN timer_sessions s ON t.timer_id = s.id "
            "WHERE t.kind='session' AND s.stopped=0 ORDER BY t.id DESC LIMIT 1").fetchone()
        if row is None:
            return None
        thread = dict(row)
    return None if session_closed(thread) else thread


def start_session(caps: dict | None = None) -> tuple[dict, bool]:
    """Returns (thread, created). An unfinished session is reopened, not duplicated;
    declared audio channels are updated on it."""
    existing = open_session_thread()
    if existing is not None:
        if caps is not None:
            db.set_caps(existing["id"], caps)
            existing = db.get_thread(existing["id"])
        return existing, False
    day = today()
    state = notebook.load()
    count = sum(1 for s in (state or {}).get("sessions", []) if s["date"] == day) + 1
    timer_id = f"{day}-seance-{count}"
    while timer.get(timer_id) is not None:  # an abandoned timer can hold the id
        count += 1
        timer_id = f"{day}-seance-{count}"
    title = f"Séance du {day}" + (f" ({count})" if count > 1 else "")
    thread = db.create_thread(kind="session", timer_id=timer_id, title=title, caps=caps)
    timer.start(timer_id)
    thread = db.get_thread(thread["id"])
    db.add_message(thread["id"], "user", "", kind="event", label="Séance démarrée",
                   parts=[{"text": kickoff(learner_name()) + "\n\n" + meta_line(thread)}])
    return thread, True


def _save_progress(thread: dict, patch) -> tuple[dict, str]:
    if not isinstance(patch, dict):
        return {"ok": False, "error": "Le patch doit être un objet JSON."}, "⚙ save_progress — patch invalide"
    try:
        if isinstance(patch.get("session"), dict) and thread.get("timer_id"):
            # Timer stop and notebook write commit or roll back together.
            with db.write() as conn:
                session = dict(patch["session"])
                measured = timer.stop_in(conn, thread["timer_id"])
                session.setdefault("timer_id", thread["timer_id"])
                if "minutes" not in session:
                    session["minutes"] = max(1, round(notebook.timing_summary(measured)["session_minutes"]))
                state = notebook.apply_update({**patch, "session": session}, conn=conn)
        else:
            state = notebook.apply_update(patch)
    except (ValueError, KeyError, TypeError) as e:
        return {"ok": False, "error": str(e)}, f"⚙ save_progress — erreur : {e}"
    label = "⚙ séance enregistrée" if "session" in patch else "⚙ progression enregistrée"
    if patch.get("cards"):
        n = len(patch["cards"])
        label += f" · {n} carte{'s' if n > 1 else ''} ajoutée{'s' if n > 1 else ''}"
        code = anki.context(state)[0].code
        for introduced in sorted({c["introduced"] for c in patch["cards"]}):
            label += f" / ⬇ {code}-{introduced}.apkg"
    if patch.get("calibration"):
        label += " · ⚙ calibrage enregistré"
    return {"ok": True, "status": notebook.status(state, notebook.day(today()))}, label


def _set_channels(thread: dict, args: dict) -> tuple[dict, str]:
    caps = {"ecoute": bool(args.get("ecoute")), "parle": bool(args.get("parle"))}
    db.set_caps(thread["id"], caps)
    thread["caps"] = json.dumps(caps, ensure_ascii=False)  # keep this turn's dict fresh
    label = (f"⚙ canaux audio : écoute {'possible' if caps['ecoute'] else 'impossible'}, "
             f"parole {'possible' if caps['parle'] else 'impossible'}")
    return {"ok": True, "caps": caps}, label


def _request_recording(thread: dict, args: dict) -> tuple[dict, str, dict]:
    caps = session_caps(thread)
    if caps is not None and not caps["parle"]:
        err = "L'apprenant a déclaré ne pas pouvoir parler pendant cette séance."
        return {"ok": False, "error": err}, f"⚙ request_recording — {err}", {}
    task, mode = args.get("task"), args.get("mode")
    instructions = str(args.get("instructions") or "").strip()
    max_seconds = args.get("max_seconds")
    if task not in TASKS or mode not in MODES or not instructions:
        err = "task/mode/instructions invalides."
        return {"ok": False, "error": err}, f"⚙ request_recording — {err}", {}
    if max_seconds is not None and not isinstance(max_seconds, int):
        max_seconds = None
    rid = db.add_request(thread["id"], task, mode, max_seconds, instructions)
    card = {"id": rid, "task": task, "mode": mode, "max_seconds": max_seconds,
            "instructions": instructions}
    return {"ok": True, "note": "La demande est affichée à Florian ; sa prochaine prise vocale y sera rattachée."}, \
        f"🎙 enregistrement demandé : {task} ({mode})", card


def import_recording(data: bytes, filename: str, task: str, mode: str, when: str,
                     note: str = "", seconds: float | None = None) -> dict:
    """Store a dictaphone file and register it like a take (ports coach.py audio)."""
    notebook.require(0 < len(data) <= MAX_IMPORT_BYTES, "Fichier audio vide ou supérieur à 200 Mo.")
    notebook.require(task in TASKS and mode in MODES, "Sujet ou mode inconnu.")
    notebook.day(when)
    notebook.require(seconds is None or notebook.number(seconds, 0, 86400), "Durée audio invalide.")
    ext = Path(filename).suffix.lower()
    check = AUDIO_MAGIC.get(ext)
    notebook.require(check is not None and check(data[:16]),
                     "Format audio attendu : WAV, MP3, M4A, OGG, WEBM ou FLAC (en-tête vérifié).")
    digest = hashlib.sha256(data).hexdigest()
    state = notebook.load()
    notebook.require(state is not None, "Aucun carnet importé.")
    for existing in state["recordings"]:
        same = (existing["date"], existing["task"], existing["mode"], existing.get("sha256"))
        if same == (when, task, mode, digest):
            return {**existing, "duplicate": True}
    rel = f"enregistrements/{when}_{task}_{mode}_{digest[:12]}{ext}"
    dest = notebook.audio_root() / rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    notebook.require(notebook.fingerprint(dest) == digest, "Copie corrompue ; import non enregistré.")
    entry = {"id": f"{when}-{task}-{digest[:6]}", "date": when, "task": task, "mode": mode,
             "path": rel, "note": note, "seconds": seconds, "sha256": digest}
    notebook.apply_update({"recordings": [entry]})  # file kept on disk if validation fails
    return entry


def _hear_recording(args: dict) -> tuple[dict, str, str | None]:
    rid = str(args.get("id") or "")
    state = notebook.load()
    rec = next((r for r in (state or {}).get("recordings", []) if r["id"] == rid), None)
    if rec is None:
        return {"ok": False, "error": "Prise inconnue."}, "⚙ hear_recording — prise inconnue", None
    if not notebook.audio_path(notebook.audio_root(), rec["path"]).is_file():
        return {"ok": False, "error": "Fichier audio absent."}, "⚙ hear_recording — fichier absent", None
    note = f"Prise {rid} jointe en audio ({rec['date']}, {rec['task']}/{rec['mode']})."
    return {"ok": True, "note": note}, f"🎙 réécoute : {rec['task']} du {rec['date']}", rec["path"]


def store_audio(data: bytes, mime: str, seconds: float | None) -> str:
    notebook.require(0 < len(data) <= MAX_AUDIO_BYTES, "Audio trop lourd ou vide.")
    notebook.require(mime.startswith("audio/"), "Type MIME audio attendu.")
    notebook.require(seconds is None or 0 < seconds <= MAX_AUDIO_SECONDS,
                     f"Prise trop longue (max {MAX_AUDIO_SECONDS} s).")
    ext = {"audio/webm": ".webm", "audio/ogg": ".ogg", "audio/mpeg": ".mp3",
           "audio/mp4": ".m4a", "audio/wav": ".wav", "audio/flac": ".flac"}.get(mime.split(";")[0], ".bin")
    rel = f"voice/{datetime.now(zone()).strftime('%Y%m%d-%H%M%S')}{ext}"
    path = notebook.audio_root() / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return rel


def register_take(thread: dict, req: dict, rel_path: str, seconds: float | None) -> None:
    """Auto-register a voice take that answers a pending request."""
    full = notebook.audio_path(notebook.audio_root(), rel_path)
    digest = notebook.fingerprint(full)
    entry = {"id": f"{today()}-{req['task']}-{digest[:6]}", "date": today(),
             "task": req["task"], "mode": req["mode"], "path": rel_path,
             "note": req["instructions"], "seconds": round(seconds, 1) if seconds else None,
             "sha256": digest}
    try:
        notebook.apply_update({"recordings": [entry]})
    except (ValueError, KeyError, TypeError):
        pass  # registration failed; the file stays on disk and the coach still hears it.
    db.resolve_request(req["id"])


def _audio_mime(rel_path: str) -> str:
    return {".webm": "audio/webm;codecs=opus", ".ogg": "audio/ogg", ".mp3": "audio/mpeg",
            ".m4a": "audio/mp4", ".wav": "audio/wav", ".flac": "audio/flac"}.get(
        Path(rel_path).suffix.lower(), "audio/webm")


def stream_events(thread: dict, event: str, *, text: str = "", audio: str = "", seconds=None):
    """User-side effects (rows, timer transitions), then the coach loop's events."""
    audio_rel = None
    if event == "start":
        pass  # kickoff row was written at session creation
    elif event == "finish":
        db.add_message(thread["id"], "user", "", kind="event", label="Fin de séance demandée",
                       parts=[{"text": finish(learner_name()) + "\n\n" + meta_line(thread)}])
    elif event == "message":
        returned = timer.user_message(thread["timer_id"]) if thread.get("timer_id") else {}
        extra = ""
        parts = []
        attachment = None
        if audio:
            state = notebook.load()
            known = next((r for r in (state or {}).get("recordings", []) if r["path"] == audio), None)
            if known:
                note = (f"[{learner_name(state)} te renvoie sa prise archivée : {known['task']} "
                        f"({known['mode']}) du {known['date']}, {known.get('seconds') or '?'} s")
            else:
                note = f"[vocal de {learner_name(state)}, {seconds or '?'} s"
                req = db.pending_request(thread["id"])
                if req:
                    register_take(thread, req, audio, seconds)
                    note += f", en réponse à la demande « {req['task']} » ({req['mode']})"
                    extra = "vocal reçu et archivé, rattaché à la demande en cours"
            note += "]"
            if text:
                note += "\n" + text
            parts = [{"text": note}]
            attachment = audio_rel = audio
        else:
            parts = [{"text": text}]
        meta = meta_line(thread, returned_after_s=returned.get("returned_after_s", 0), extra=extra)
        wire = [{"text": meta + "\n\n" + parts[0]["text"]}] + parts[1:]
        db.add_message(thread["id"], "user", text, kind="audio" if audio else "message",
                       parts=wire, attachment=attachment)
    contents = wire_contents(thread["id"])
    if audio_rel:
        # The audio rides inline on this turn only; history keeps the text marker.
        full = notebook.audio_path(notebook.audio_root(), audio_rel)
        contents[-1]["parts"].append({"inlineData": {
            "mimeType": _audio_mime(audio_rel),
            "data": base64.b64encode(full.read_bytes()).decode()}})
    yield from _loop(thread, contents)


def _generate(contents: list[dict], **kwargs):
    """Run one blocking model turn in a thread, yielding text events as chunks arrive."""
    chunks, result = queue.Queue(), {}

    def run():
        try:
            result["parts"] = gemini.generate_turn(contents, on_text=chunks.put, **kwargs)
        except Exception as e:
            result["error"] = e
        finally:
            chunks.put(None)

    threading.Thread(target=run, daemon=True).start()
    while (chunk := chunks.get()) is not None:
        yield {"type": "text", "text": chunk}
    if "error" in result:
        raise result["error"]
    return result["parts"]


def _loop(thread: dict, contents: list[dict]):
    """Model turns until a call-free reply. Yields text/tool/card/timer/done events."""
    is_session = thread.get("kind") == "session" and not session_closed(thread)
    state = notebook.load()
    language = languages.get(state.get("language") or "") if state else None
    if thread.get("kind") == "side":
        system = side_prompt(thread)
    elif is_session:
        system = system_prompt(thread)
    else:
        system = chat_system(language) if language else CHAT_FALLBACK
    session_tools = coach_tools(language) if (is_session and language) else None
    model_text = ""
    for _ in range(6):
        parts = yield from _generate(contents, system=system, tools=session_tools)
        model_text = "".join(p["text"] for p in parts if p.get("text") and not p.get("thought"))
        calls = [p["functionCall"] for p in parts if "functionCall" in p]
        db.add_message(thread["id"], "model", strip_marks(model_text), parts=parts)
        if not calls:
            break
        contents.append({"role": "model", "parts": parts})
        responses, labels = [], []
        for call in calls:
            name, args = call.get("name", ""), call.get("args") or {}
            audio_rel = None
            if name == "save_progress":
                result, label = _save_progress(thread, args)
                card = None
            elif name == "request_recording":
                result, label, card = _request_recording(thread, args)
            elif name == "hear_recording":
                result, label, audio_rel = _hear_recording(args)
                card = None
            elif name == "set_channels":
                result, label = _set_channels(thread, args)
                card = None
            else:
                result, label, card = {"error": f"outil inconnu : {name}"}, f"⚙ {name} — inconnu", None
            responses.append({"functionResponse": {"name": name, "response": result}})
            if audio_rel:
                # The archived take rides inline with the tool answer, so the
                # model hears it on the next turn like a fresh vocal.
                full = notebook.audio_path(notebook.audio_root(), audio_rel)
                responses.append({"inlineData": {
                    "mimeType": _audio_mime(audio_rel),
                    "data": base64.b64encode(full.read_bytes()).decode()}})
            labels.append(label)
            yield {"type": "tool", "label": label}
            if card:
                yield {"type": "card", "card": card}
        db.add_message(thread["id"], "user", "", kind="tool", parts=responses,
                       label=" / ".join(labels))
        contents.append({"role": "user", "parts": responses})
    else:
        yield {"type": "error", "message": "trop d'appels d'outils à la suite"}
    if is_session and thread.get("timer_id"):
        timer.coach_stream_end(thread["timer_id"], extract_task(model_text))
        yield {"type": "timer", "timer": timer.summary(thread["timer_id"])}
    yield {"type": "done"}
