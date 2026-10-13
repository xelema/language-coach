"""Session timer on timer_sessions/timer_periods, driven by chat events.

Semantics of the server-side timer: kinds coach/learner/pause,
periods contiguous, at most one unstopped session, pause keeps the period to
resume into. Transitions are automatic: a finished coach stream opens a
learner window, a message from the learner opens a coach period.
"""
from datetime import datetime, timezone

from . import db, notebook

LONG_PERIOD_S = 1200  # >20 min without a signal: ask before trusting the duration.


def _stamp(now=None) -> str:
    if isinstance(now, str):
        return notebook.instant(now).isoformat()
    return notebook.stamp(now or datetime.now(timezone.utc))


def _session(conn, session_id: str) -> dict | None:
    row = conn.execute(
        "SELECT id, stopped, resume_kind, resume_task FROM timer_sessions WHERE id=?",
        (session_id,)).fetchone()
    if row is None:
        return None
    periods = [dict(p) for p in conn.execute(
        "SELECT kind, task, start, end FROM timer_periods WHERE session_id=? ORDER BY idx",
        (session_id,))]
    session = {"id": row["id"], "stopped": bool(row["stopped"]), "periods": periods}
    if row["resume_kind"] is not None:
        session["resume_period"] = {"kind": row["resume_kind"], "task": row["resume_task"]}
    return session


def get(session_id: str) -> dict | None:
    with db.connect() as conn:
        return _session(conn, session_id)


def active() -> dict | None:
    """The single unstopped timer session, if any."""
    with db.connect() as conn:
        row = conn.execute("SELECT id FROM timer_sessions WHERE stopped=0 LIMIT 1").fetchone()
        return _session(conn, row["id"]) if row else None


def summary(session_id: str, now=None) -> dict | None:
    session = get(session_id)
    return notebook.timing_summary(session, now) if session else None


def _open(conn, session, kind, task, stamp):
    period = session["periods"][-1]
    conn.execute(
        "UPDATE timer_periods SET end=? WHERE session_id=? AND idx=?",
        (stamp, session["id"], len(session["periods"]) - 1))
    conn.execute(
        "INSERT INTO timer_periods(session_id, idx, kind, task, start) VALUES(?,?,?,?,?)",
        (session["id"], len(session["periods"]), kind, task, stamp))
    return period


def _mutate(session_id: str, action, now=None):
    stamp = _stamp(now)
    with db.write() as conn:
        session = _session(conn, session_id)
        notebook.require(session is not None, "Chronomètre inconnu.")
        if session["stopped"]:
            return session  # start/stop on a stopped timer is a no-op.
        period = session["periods"][-1]
        notebook.require(
            notebook.instant(stamp) >= notebook.instant(period["start"]),
            "Horloge reculée : aucun changement sauvegardé.")
        if action[0] == "pause":
            if period["kind"] != "pause":
                conn.execute(
                    "UPDATE timer_sessions SET resume_kind=?, resume_task=? WHERE id=?",
                    (period["kind"], period["task"], session_id))
                _open(conn, session, "pause", action[1] or "pause", stamp)
        elif action[0] == "resume":
            notebook.require(period["kind"] == "pause", "Le chronomètre n'est pas en pause.")
            prev = conn.execute(
                "SELECT resume_kind, resume_task FROM timer_sessions WHERE id=?",
                (session_id,)).fetchone()
            conn.execute(
                "UPDATE timer_sessions SET resume_kind=NULL, resume_task=NULL WHERE id=?",
                (session_id,))
            _open(conn, session, prev["resume_kind"], prev["resume_task"], stamp)
        elif action[0] == "learner":
            if period["kind"] == "pause":
                # Stream ended during a pause: resume lands on the learner window.
                conn.execute(
                    "UPDATE timer_sessions SET resume_kind='learner', resume_task=? WHERE id=?",
                    (action[1], session_id))
            elif period["kind"] != "learner" or period["task"] != action[1]:
                _open(conn, session, "learner", action[1], stamp)
        else:  # stop
            _stop(conn, session, stamp)
        notebook.read_timers(conn)  # validates every invariant, rolls back on failure
        return _session(conn, session_id)


def _stop(conn, session: dict, stamp: str) -> None:
    conn.execute(
        "UPDATE timer_periods SET end=? WHERE session_id=? AND idx=?",
        (stamp, session["id"], len(session["periods"]) - 1))
    conn.execute("UPDATE timer_sessions SET stopped=1 WHERE id=?", (session["id"],))


def stop_in(conn, session_id: str, now=None) -> dict:
    """Stop inside a caller's write transaction, so a rolled-back save leaves
    the timer running. Returns the session, stopped."""
    stamp = _stamp(now)
    session = _session(conn, session_id)
    notebook.require(session is not None, "Chronomètre inconnu.")
    if session["stopped"]:
        return session
    period = session["periods"][-1]
    notebook.require(
        notebook.instant(stamp) >= notebook.instant(period["start"]),
        "Horloge reculée : aucun changement sauvegardé.")
    _stop(conn, session, stamp)
    notebook.read_timers(conn)
    return _session(conn, session_id)


def start(session_id: str, now=None) -> dict:
    """Idempotent: an already-running timer with this id is returned as-is."""
    stamp = _stamp(now)
    with db.write() as conn:
        running = conn.execute("SELECT id FROM timer_sessions WHERE stopped=0").fetchone()
        notebook.require(
            running is None or running["id"] == session_id,
            "Une autre séance est active : la reprendre ou l'arrêter explicitement.")
        session = _session(conn, session_id)
        if session is None:
            conn.execute("INSERT INTO timer_sessions(id, stopped) VALUES(?,0)", (session_id,))
            conn.execute(
                "INSERT INTO timer_periods(session_id, idx, kind, task, start) VALUES(?,0,'coach','',?)",
                (session_id, stamp))
            notebook.read_timers(conn)
            return _session(conn, session_id)
        notebook.require(not session["stopped"], "Cette séance est terminée : nouvel ID requis.")
        return session


def coach_stream_end(session_id: str, task: str = "", now=None) -> dict:
    """The coach finished talking: open a learner window named after the exercise."""
    return _mutate(session_id, ("learner", task or "réponse"), now)


def user_message(session_id: str, now=None) -> dict:
    """The learner wrote: open a coach period. Returns the closing window's seconds."""
    stamp = _stamp(now)
    result = {"returned_after_s": 0.0}
    with db.write() as conn:
        session = _session(conn, session_id)
        notebook.require(session is not None, "Chronomètre inconnu.")
        if session["stopped"]:
            return result
        period = session["periods"][-1]
        if period["kind"] == "learner":
            secs = (notebook.instant(stamp) - notebook.instant(period["start"])).total_seconds()
            if secs > LONG_PERIOD_S:
                result["returned_after_s"] = secs
        if period["kind"] == "pause":
            conn.execute(
                "UPDATE timer_sessions SET resume_kind=NULL, resume_task=NULL WHERE id=?",
                (session_id,))
        _open(conn, session, "coach", "", stamp)
        notebook.read_timers(conn)
    return result


def pause(session_id: str, task: str = "", now=None) -> dict:
    return _mutate(session_id, ("pause", task), now)


def resume(session_id: str, now=None) -> dict:
    return _mutate(session_id, ("resume",), now)


def stop(session_id: str, now=None) -> dict:
    return _mutate(session_id, ("stop",), now)
