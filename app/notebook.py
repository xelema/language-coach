"""Le carnet : la progression d'un apprenant, en JSON, versionnée dans SQLite.

Chaque sauvegarde acceptée ajoute une ligne à `notebook_versions` ; le carnet
courant est la dernière ligne, un patch refusé n'écrit rien. La langue et le
profil viennent des language packs, donc ce module ne connaît aucune langue en
particulier et l'échéance est facultative.
"""
import hashlib
import json
import math
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import db, languages
from .auth import data_dir

SKILLS = {"ecoute": "Écoute", "oral": "Oral", "ecrit": "Messages", "registre": "Registres"}
INTERVALS = (1, 3, 7, 14, 30)
# Ressenti déclaré à la clôture d'une séance : c'est lui qui déclenche
# l'auto-critique du coach et le réglage de la séance suivante.
FELT = ("trop_facile", "bien", "trop_dur")

# Le profil créé à l'initialisation : ce qui rend le coaching pertinent sans
# rien supposer de l'apprenant.
PROFILE_KEYS = ("name", "objective", "level", "level_verified", "cadence", "registers", "context",
                "audio")



def _optional_text(value, name, limit=2000):
    require(value is None or (isinstance(value, str) and len(value) <= limit),
            f"Champ texte invalide : {name}.")


def validate_profile(profile, language) -> None:
    """Le profil est ce que l'initialisation a demandé : objectif, niveau
    déclaré, cadence, registres visés, contexte libre."""
    require(isinstance(profile, dict), "Profil d'apprentissage attendu.")
    require(set(profile) <= set(PROFILE_KEYS), "Champ de profil inconnu.")
    for field in ("objective", "level"):
        text_field(profile.get(field), field)
    levels = [level.code for level in language.levels]
    require(profile["level"] in levels, f"Niveau inconnu pour le {language.name} : {profile['level']}.")
    _optional_text(profile.get("name"), "name", 60)
    _optional_text(profile.get("context"), "context", 4000)
    _optional_text(profile.get("cadence"), "cadence", 200)
    verified = profile.get("level_verified")
    require(verified in (None, "") or verified in levels, "Niveau vérifié inconnu.")
    registers = profile.get("registers") or list(language.register_ids)
    require(isinstance(registers, list) and registers, "Registres visés attendus.")
    for register in registers:
        require(register in language.register_ids,
                f"Registre inconnu pour le {language.name} : {register}.")
    audio = profile.get("audio")
    require(audio is None or (isinstance(audio, dict) and set(audio) == {"ecoute", "parle"}
                              and all(type(value) is bool for value in audio.values())),
            "Capacités audio attendues : {ecoute, parle} en booléens.")


def new_notebook(language_code: str, profile: dict, start: str | None = None,
                 resources: list | None = None, target: str | None = None) -> dict:
    """Carnet initial créé par l'initialisation, sans échéance imposée.
    `resources` = les vidéos que l'apprenant a validées lui-même ; `target` =
    l'échéance, seulement si l'apprenant en a donné une."""
    language = languages.get(language_code)
    filled = {"name": "", "objective": "", "level": "A0", "level_verified": None,
              "cadence": "", "registers": list(language.register_ids), "context": "",
              "audio": None, **(profile or {})}
    validate_profile(filled, language)
    state = {
        "version": 1, "language": language.code, "profile": filled,
        "review_engine": "local", "start": day(start or date.today().isoformat()).isoformat(),
        "target": day(target).isoformat() if target else None,
        "next": "Première séance : diagnostic court pour situer le niveau réel, puis objectif de séance.",
        "resume": None, "prep": None,
        "sessions": [], "cards": [], "reviews": [], "recordings": [], "checkpoints": [],
        "calibration": [], "resources": list(resources or []),
    }
    validate(state)
    return state


def require(condition, message):
    if not condition:
        raise ValueError(message)


def day(value):
    require(isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value), "Date attendue : AAAA-MM-JJ.")
    return date.fromisoformat(value)


def text_field(value, name, empty=False):
    require(isinstance(value, str) and len(value) <= 20000 and (empty or value.strip()), f"Champ texte invalide : {name}.")


def number(value, minimum, maximum):
    return type(value) in (int, float) and math.isfinite(value) and minimum <= value <= maximum


def stamp(value=None):
    value = value or datetime.now(timezone.utc)
    require(value.tzinfo is not None, "Horloge sans fuseau horaire.")
    return value.astimezone(timezone.utc).isoformat()


def instant(value):
    result = datetime.fromisoformat(value)
    require(result.tzinfo is not None, "Horodatage sans fuseau.")
    return result


def fingerprint(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audio_root():
    return data_dir() / "audio"


def audio_path(root, value):
    require(isinstance(value, str), "Chemin audio invalide.")
    path = (root / value).resolve()
    require(path.is_relative_to(Path(root).resolve()), "Audio hors du dossier enregistrements.")
    return path


def validate(state):
    require(isinstance(state, dict) and state.get("version") == 1, "Version du carnet inconnue.")
    require(state.get("review_engine", "local") in ("local", "anki"), "Moteur de révision inconnu.")
    language = languages.get(state.get("language") or "")
    validate_profile(state.get("profile"), language)
    start = day(state["start"])
    target = state.get("target")
    require(target is None or day(target) > start, "Échéance antérieure au début.")
    text_field(state["next"], "next")
    require(state["resume"] is None or isinstance(state["resume"], str), "resume doit être un texte ou null.")
    require(state.get("prep") is None or isinstance(state["prep"], str), "prep doit être un texte ou null.")
    for collection in ("sessions", "cards", "reviews", "recordings", "checkpoints", "calibration",
                       "resources"):
        items = state[collection]
        require(isinstance(items, list), f"{collection} doit être une liste.")
        seen = set()
        for item in items:
            require(isinstance(item, dict), "Entrée invalide.")
            require("id" in item, f"Champ manquant : id ({collection}).")
            text_field(item["id"], "id")
            require(item["id"] not in seen, f"ID répété : {item['id']}.")
            seen.add(item["id"])
            if collection != "cards":
                require("date" in item, f"Champ manquant : date ({collection}).")
                day(item["date"])
    for s in state["sessions"]:
        for field in ("minutes", "kind", "summary", "evidence"):
            require(field in s, f"Champ manquant : {field} (sessions).")
        require(number(s["minutes"], 1, 1440), "Durée réelle attendue entre 1 et 1440 minutes.")
        if "completed" in s:
            require(type(s["completed"]) is bool, "completed doit être un booléen.")
            if s["completed"]:
                text_field(s.get("completion_evidence"), "completion_evidence")
        require(s["kind"] in ("diagnostic", "apprentissage", "consolidation", "bilan", "partielle"), "Type de séance inconnu.")
        for field in ("summary", "evidence"):
            text_field(s[field], field)
        require(isinstance(s.get("errors", []), list), "errors doit être une liste.")
    for c in state["cards"]:
        for field in ("prompt", "answer", "source", "register", "skill", "level", "due"):
            require(field in c, f"Champ manquant : {field} (cards).")
        for field in ("prompt", "answer", "source"):
            text_field(c[field], field)
        require(c["register"] in language.register_ids, "Registre de carte inconnu pour cette langue.")
        require(c["skill"] in SKILLS, "Compétence de carte inconnue.")
        require(type(c["level"]) is int and 0 <= c["level"] <= len(INTERVALS), "Palier de révision invalide.")
        day(c["due"])
    card_ids = {c["id"] for c in state["cards"]}
    reviewed = set()
    for r in state["reviews"]:
        for field in ("card", "rating"):
            require(field in r, f"Champ manquant : {field} (reviews).")
        require(r["card"] in card_ids and r["rating"] in ("echec", "aide", "difficile", "reussi"), "Révision invalide.")
        key = (r["card"], r["date"])
        require(key not in reviewed, "Une seule révision comptabilisée par carte et par jour.")
        reviewed.add(key)
    for r in state["recordings"]:
        for field in ("task", "mode", "path", "note", "seconds"):
            require(field in r, f"Champ manquant : {field} (recordings).")
        require(r["task"] in ("presentation", "journee", "film", "lecture", "conversation"), "Sujet audio inconnu.")
        require(r["mode"] in ("spontane", "lecture", "entraine"), "Mode audio inconnu.")
        text_field(r["path"], "path")
        text_field(r["note"], "note", empty=True)
        require(r["seconds"] is None or number(r["seconds"], 0, 86400), "Durée audio invalide.")
    for c in state["checkpoints"]:
        for field in ("scores", "independent", "unseen", "audio_assessed", "evidence"):
            require(field in c, f"Champ manquant : {field} (checkpoints).")
        require(type(c.get("provisional", False)) is bool, "provisional doit être un booléen.")
        require(set(c["scores"]) == set(SKILLS), "Le bilan exige les quatre compétences (null si non évaluée).")
        for flag in ("independent", "unseen", "audio_assessed"):
            require(type(c[flag]) is bool, f"{flag} doit être un booléen.")
        require(isinstance(c["evidence"], dict), "Preuves attendues par compétence.")
        for skill, score in c["scores"].items():
            require(score is None or (type(score) is int and 0 <= score <= 4), "Score entier entre 0 et 4, ou null.")
            if score is not None:
                text_field(c["evidence"].get(skill), f"preuve {skill}")
        require(c["scores"]["oral"] is None or c["audio_assessed"], "Sans écoute réelle de l'audio, le score oral doit être null.")

    for c in state["calibration"]:
        require(c.get("felt") in FELT, "Ressenti attendu : trop_facile, bien ou trop_dur.")
        for field in ("observation", "change"):
            text_field(c.get(field), field)
        _optional_text(c.get("carry"), "carry", 2000)
        require(type(c.get("applied", False)) is bool, "applied doit être un booléen.")

    for r in state["resources"]:
        text_field(r.get("title"), "title")
        text_field(r.get("url"), "url")
        require(re.match(r"^https?://", r["url"]), "URL de ressource attendue (http/https).")
        _optional_text(r.get("channel"), "channel", 200)
        _optional_text(r.get("note"), "note", 500)
        require(r.get("duration") is None or number(r["duration"], 0, 86400),
                "Durée de vidéo invalide.")


def validate_timers(data):
    """Invariant checks of the timer document rebuilt from the rows, on any source."""
    require(data.get("version") == 1 and isinstance(data.get("sessions"), list), "Chronomètre invalide : conserver le fichier et vérifier sa sauvegarde.")
    ids = set()
    for session in data["sessions"]:
        text_field(session["id"], "id du chronomètre")
        require(session["id"] not in ids, "Chronomètre dupliqué.")
        ids.add(session["id"])
        require(isinstance(session["periods"], list) and session["periods"], "Périodes manquantes.")
        require(type(session["stopped"]) is bool, "Statut du chronomètre invalide.")
        require(session["stopped"] or session["periods"][-1]["end"] is None,
                "Chronomètre actif sans période ouverte.")
        if not session["stopped"] and session["periods"][-1]["kind"] == "pause":
            previous = session.get("resume_period", {})
            require(previous.get("kind") in ("coach", "learner"), "État de reprise manquant.")
            text_field(previous.get("task"), "task de reprise", empty=True)
        for index, period in enumerate(session["periods"]):
            require(period["kind"] in ("coach", "learner", "pause"), "Type de période inconnu.")
            text_field(period["task"], "task", empty=True)
            start = instant(period["start"])
            if period["end"] is not None:
                require(instant(period["end"]) >= start, "Horloge reculée : mesure à vérifier.")
            else:
                require(index == len(session["periods"]) - 1 and not session["stopped"], "Période ouverte invalide.")
            if index:
                require(session["periods"][index - 1]["end"] == period["start"], "Périodes discontinues.")
    require(sum(not s["stopped"] for s in data["sessions"]) <= 1, "Plusieurs chronomètres actifs.")


def timing_summary(session, now=None):
    end_now = instant(stamp(now))
    totals = {"coach": 0.0, "learner": 0.0, "pause": 0.0}
    tasks = []
    uncertain = False
    for period in session["periods"]:
        seconds = ((instant(period["end"]) if period["end"] else end_now) - instant(period["start"])).total_seconds()
        require(seconds >= 0, "L'horloge a reculé ; mesure à vérifier avant sauvegarde.")
        totals[period["kind"]] += seconds
        # ponytail: une fenêtre >20 min demande confirmation ; pas de détection automatique de présence.
        uncertain |= period["kind"] != "pause" and seconds > 1200
        if period["kind"] == "learner":
            tasks.append({"task": period["task"], "seconds": round(seconds, 2)})
    return {"id": session["id"], "stopped": session["stopped"],
            "state": "stopped" if session["stopped"] else session["periods"][-1]["kind"],
            "elapsed_minutes": round(sum(totals.values()) / 60, 2),
            "session_minutes": round((totals["coach"] + totals["learner"]) / 60, 2),
            "response_minutes": round(totals["learner"] / 60, 2),
            "coach_minutes": round(totals["coach"] / 60, 2), "pause_minutes": round(totals["pause"] / 60, 2),
            "needs_confirmation": uncertain, "responses": tasks,
            "meaning": "Temps écoulés mesurés. Les fenêtres de réponse incluent lecture, réflexion, frappe et éventuelle inactivité ; ce n'est pas une mesure certaine de l'attention."}


def read_timers(conn):
    """Rebuild the chronometre.json document from timer rows and validate it."""
    sessions = []
    for row in conn.execute("SELECT id, stopped, resume_kind, resume_task FROM timer_sessions ORDER BY rowid"):
        periods = [dict(p) for p in conn.execute(
            "SELECT kind, task, start, end FROM timer_periods WHERE session_id=? ORDER BY idx", (row["id"],))]
        session = {"id": row["id"], "stopped": bool(row["stopped"]), "periods": periods}
        if row["resume_kind"] is not None:
            session["resume_period"] = {"kind": row["resume_kind"], "task": row["resume_task"]}
        sessions.append(session)
    data = {"version": 1, "sessions": sessions}
    validate_timers(data)
    return data


def put_timer_session(conn, session):
    """Insert or replace one timer session and its periods."""
    resume = session.get("resume_period") or {}
    conn.execute(
        "INSERT OR REPLACE INTO timer_sessions(id, stopped, resume_kind, resume_task) VALUES(?,?,?,?)",
        (session["id"], 1 if session["stopped"] else 0, resume.get("kind"), resume.get("task")))
    conn.execute("DELETE FROM timer_periods WHERE session_id=?", (session["id"],))
    conn.executemany(
        "INSERT INTO timer_periods(session_id, idx, kind, task, start, end) VALUES(?,?,?,?,?,?)",
        [(session["id"], i, p["kind"], p["task"], p["start"], p["end"]) for i, p in enumerate(session["periods"])])


def _load(conn):
    row = conn.execute("SELECT json FROM notebook_versions ORDER BY id DESC LIMIT 1").fetchone()
    if row is None:
        return None
    state = json.loads(row["json"])
    validate(state)
    return state


def load():
    """Latest notebook state, or None when nothing was imported yet."""
    with db.connect() as conn:
        return _load(conn)


def version_count():
    with db.connect() as conn:
        return conn.execute("SELECT COUNT(*) AS n FROM notebook_versions").fetchone()["n"]


def insert_version(conn, state):
    validate(state)
    conn.execute("INSERT INTO notebook_versions(json, saved_at) VALUES(?,?)",
                 (json.dumps(state, ensure_ascii=False), stamp()))


def apply_update(patch, conn=None):
    """Apply a patch inside the caller's transaction when conn is given, so a
    rejected save can roll back companion writes (ex. the timer stop)."""
    require(isinstance(patch, dict), "La mise à jour doit être un objet JSON.")
    require(set(patch) <= {"session", "cards", "reviews", "checkpoint", "next", "resume", "prep",
                           "recordings", "calibration", "profile", "target", "resources"},
            "Champ de mise à jour inconnu.")
    if conn is None:
        with db.write() as conn:
            return _apply(conn, patch)
    return _apply(conn, patch)


def _apply(conn, patch):
    state = _load(conn)
    require(state is not None, "Aucun carnet : commencer par l'initialisation.")
    language = languages.get(state.get("language") or "")
    require(not patch.get("reviews") or state.get("review_engine") != "anki", "Anki gère les révisions ; conserver les observations dans la séance, sans second calendrier.")
    if "session" in patch and patch["session"].get("timer_id"):
        session = dict(patch["session"])
        require(not any(s.get("timer_id") == session["timer_id"] for s in state["sessions"]),
                "Ce chronomètre est déjà rattaché à une séance enregistrée.")
        measured = next((s for s in read_timers(conn)["sessions"] if s["id"] == session["timer_id"]), None)
        require(measured is not None and measured["stopped"], "Arrêter le chronomètre de la séance avant sa sauvegarde.")
        session["timing"] = timing_summary(measured)
        if session["timing"]["needs_confirmation"]:
            text_field(session.get("time_confirmation"), "time_confirmation : durée confirmée par l'apprenant après une longue absence")
        patch = {**patch, "session": session}
    for key, collection in (("session", "sessions"), ("checkpoint", "checkpoints")):
        if key in patch:
            state[collection].append(patch[key])
    for c in patch.get("cards", []):
        require(not {"level", "due"}.intersection(c), "Les échéances des nouvelles cartes sont calculées automatiquement.")
        require("introduced" in c, "Date introduced manquante.")
        state["cards"].append({**c, "level": 0, "due": (day(c["introduced"]) + timedelta(days=1)).isoformat()})
    for r in patch.get("reviews", []):
        for field in ("card", "date", "rating"):
            require(field in r, f"Champ manquant : {field} (reviews).")
        card = next((c for c in state["cards"] if c["id"] == r["card"]), None)
        require(card is not None, "Carte inconnue.")
        require(day(r["date"]) >= day(card["due"]), "Carte pas encore due : répétition possible, sans modifier l'échéance.")
        require(r["rating"] in ("echec", "aide", "difficile", "reussi"), "Résultat de révision inconnu.")
        if r["rating"] == "reussi":
            interval = INTERVALS[min(card["level"], len(INTERVALS) - 1)]
            card["level"] = min(len(INTERVALS), card["level"] + 1)
        else:
            interval = 1
            if r["rating"] in ("echec", "aide"):
                card["level"] = 0
        card["due"] = (day(r["date"]) + timedelta(days=interval)).isoformat()
        state["reviews"].append(r)
    for r in patch.get("recordings", []):
        state["recordings"].append(r)
    # Auto-critique de séance : une liste, comme les cartes et les révisions.
    for c in patch.get("calibration", []):
        state["calibration"].append(c)
    # Vidéos validées plus tard : même règle, on n'écrase jamais les précédentes.
    for r in patch.get("resources", []):
        state["resources"].append(r)
    for key in ("next", "resume", "prep"):
        if key in patch:
            state[key] = patch[key]
    if "profile" in patch:
        # Le profil se modifie en cours de route (objectif précisé, cadence
        # ajustée) ; la langue, elle, est fixée à l'initialisation.
        validate_profile(patch["profile"], language)
        state["profile"] = patch["profile"]
    if "target" in patch:
        target = patch["target"]
        require(target is None or day(target) > day(state["start"]),
                "Échéance antérieure au début (laisser vide pour aucune échéance).")
        state["target"] = target
    insert_version(conn, state)
    return state


def progress(state):
    best = {s: 0 for s in SKILLS}
    for c in state["checkpoints"]:
        if c["independent"] and c["unseen"] and not c.get("provisional"):
            for s, value in c["scores"].items():
                if value is not None:
                    best[s] = max(best[s], value)
    rank = ("Placement", "Bronze", "Argent", "Or", "Platine")[min(best.values())]
    return best, sum(best.values()) * 25, rank


def daily_recap(state, today):
    """Un jour sans trace n'est manqué qu'une fois terminé, dans la campagne."""
    result = []
    current = day(state["start"])
    # Sans échéance, la chronologie s'arrête à aujourd'hui : un jour n'est
    # manqué qu'une fois terminé, et rien n'est promis sur l'avenir.
    end = min(today, day(state["target"])) if state.get("target") else today
    while current <= end:
        sessions = [s for s in state["sessions"] if s["date"] == current.isoformat()]
        minutes = sum(s["minutes"] for s in sessions)
        complete = any(s.get("completed", s["minutes"] >= 60) for s in sessions)
        kind = "complete" if complete else "partielle" if minutes else "sans_trace" if current < today else "a_faire"
        result.append({"date": current.isoformat(), "minutes": minutes, "status": kind,
                       "recaps": [s["summary"] for s in sessions]})
        current += timedelta(days=1)
    return result


def status(state, today):
    best, lp, rank = progress(state)
    language = languages.get(state.get("language") or "")
    profile = state.get("profile") or {}
    elapsed = (today - day(state["start"])).days
    # Plus de campagne bornée : la semaine est un simple repère de rythme, et
    # seules les 30 dernières journées sont recensées pour les absences.
    week = max(1, elapsed // 7 + 1)
    days = daily_recap(state, today)
    missed = [d["date"] for d in days[-30:] if d["status"] == "sans_trace"]
    target = state.get("target")
    return {"date": today.isoformat(), "semaine": week,
            "langue": language.name, "langue_code": language.code, "depuis": state["start"],
            "echeance": target,
            "jours_restants": max(0, (day(target) - today).days) if target else None,
            "profil": {"objectif": profile.get("objective", ""), "niveau_declare": profile.get("level"),
                       "niveau_verifie": profile.get("level_verified"),
                       "cadence": profile.get("cadence", ""), "contexte": profile.get("context", "")},
            "minutes_pratiquees": sum(s["minutes"] for s in state["sessions"]), "rang": rank, "lp": lp,
            "jours_sans_trace": missed, "recap_7_derniers_jours": days[-7:],
            "meilleurs_paliers": best, "resume": state["resume"], "prochaine_action": state["next"],
            "calibrage": state["calibration"][-5:],
            "ressources_videos": [{"titre": r["title"], "chaine": r.get("channel", ""),
                                   "url": r["url"], "duree_s": r.get("duration"),
                                   "note": r.get("note", "")} for r in state["resources"]],
            "review_engine": state.get("review_engine", "local"),
            "cartes_dues": [] if state.get("review_engine") == "anki" else sorted((c for c in state["cards"] if day(c["due"]) <= today), key=lambda c: c["due"])}


def report_data(state, today):
    """Everything the /progres page renders, in one payload (ports bilan.html's report)."""
    info = status(state, today)
    recordings = [{**r, "missing": not audio_path(audio_root(), r["path"]).is_file()}
                  for r in sorted(state["recordings"], key=lambda r: r["date"])]
    return {"date": today.isoformat(), "start": state["start"], "target": state.get("target"),
            "language": state.get("language"), "profile": state.get("profile"),
            "semaine": info["semaine"], "rang": info["rang"], "lp": info["lp"],
            "meilleurs_paliers": info["meilleurs_paliers"],
            "minutes_pratiquees": info["minutes_pratiquees"],
            "jours_restants": info["jours_restants"], "jours_sans_trace": info["jours_sans_trace"],
            "resume": info["resume"], "next": info["prochaine_action"],
            "review_engine": info["review_engine"], "cartes_dues": len(info["cartes_dues"]),
            "days": daily_recap(state, today), "sessions": state["sessions"],
            "checkpoints": sorted(state["checkpoints"], key=lambda c: c["date"]),
            "recordings": recordings}
