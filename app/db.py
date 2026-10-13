"""SQLite storage: threads and messages, notebook versions, timer periods."""
import contextlib
import json
import sqlite3
import threading
from datetime import datetime, timezone

from .auth import data_dir

_SCHEMA = """
CREATE TABLE IF NOT EXISTS threads(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  title TEXT NOT NULL DEFAULT '',
  kind TEXT NOT NULL DEFAULT 'chat',
  timer_id TEXT,
  parent_id INTEGER REFERENCES threads(id),
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id INTEGER NOT NULL REFERENCES threads(id),
  role TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'message',
  text TEXT NOT NULL,
  parts TEXT,
  attachment TEXT,
  label TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notebook_versions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  json TEXT NOT NULL,
  saved_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS timer_sessions(
  id TEXT PRIMARY KEY,
  stopped INTEGER NOT NULL,
  resume_kind TEXT,
  resume_task TEXT
);
CREATE TABLE IF NOT EXISTS timer_periods(
  session_id TEXT NOT NULL REFERENCES timer_sessions(id),
  idx INTEGER NOT NULL,
  kind TEXT NOT NULL,
  task TEXT NOT NULL,
  start TEXT NOT NULL,
  end TEXT,
  PRIMARY KEY(session_id, idx)
);
CREATE TABLE IF NOT EXISTS recording_requests(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  thread_id INTEGER NOT NULL REFERENCES threads(id),
  task TEXT NOT NULL,
  mode TEXT NOT NULL,
  max_seconds INTEGER,
  instructions TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL
);
"""

# Columns added after the first deploy: (table, name, ddl fragment).
_MIGRATIONS = [
    ("threads", "kind", "ALTER TABLE threads ADD COLUMN kind TEXT NOT NULL DEFAULT 'chat'"),
    ("threads", "timer_id", "ALTER TABLE threads ADD COLUMN timer_id TEXT"),
    ("threads", "parent_id", "ALTER TABLE threads ADD COLUMN parent_id INTEGER REFERENCES threads(id)"),
    ("messages", "kind", "ALTER TABLE messages ADD COLUMN kind TEXT NOT NULL DEFAULT 'message'"),
    ("messages", "parts", "ALTER TABLE messages ADD COLUMN parts TEXT"),
    ("messages", "attachment", "ALTER TABLE messages ADD COLUMN attachment TEXT"),
    ("messages", "label", "ALTER TABLE messages ADD COLUMN label TEXT"),
    ("threads", "caps", "ALTER TABLE threads ADD COLUMN caps TEXT"),
]

_write_lock = threading.Lock()


@contextlib.contextmanager
def connect():
    db = sqlite3.connect(data_dir() / "coach.db")
    db.row_factory = sqlite3.Row
    db.executescript(_SCHEMA)
    for table, column, ddl in _MIGRATIONS:
        cols = {r["name"] for r in db.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            db.execute(ddl)
    try:
        yield db
        db.commit()
    finally:
        db.close()


@contextlib.contextmanager
def write():
    """Serialized write transaction: in-process lock plus BEGIN IMMEDIATE."""
    with _write_lock:
        with connect() as db:
            db.execute("BEGIN IMMEDIATE")
            yield db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def list_threads() -> list[dict]:
    with connect() as db:
        # Side threads belong to their session and never appear in the drawer.
        return [dict(r) for r in db.execute(
            "SELECT * FROM threads WHERE kind != 'side' ORDER BY id DESC")]


def create_thread(kind: str = "chat", timer_id: str | None = None, title: str = "",
                  parent_id: int | None = None, caps: dict | None = None) -> dict:
    with connect() as db:
        cur = db.execute(
            "INSERT INTO threads(title, kind, timer_id, parent_id, caps, created_at) VALUES(?,?,?,?,?,?)",
            (title, kind, timer_id, parent_id,
             json.dumps(caps, ensure_ascii=False) if caps is not None else None, _now()),
        )
        return {"id": cur.lastrowid, "title": title, "kind": kind, "timer_id": timer_id,
                "parent_id": parent_id, "caps": caps}


def set_caps(thread_id: int, caps: dict) -> None:
    """Audio channels declared for a session: {ecoute, parle}."""
    with connect() as db:
        db.execute("UPDATE threads SET caps=? WHERE id=?",
                   (json.dumps(caps, ensure_ascii=False), thread_id))


def side_thread(main_id: int) -> dict:
    """The session's side thread for questions, created on first access."""
    with write() as db:
        row = db.execute(
            "SELECT * FROM threads WHERE parent_id=? AND kind='side'", (main_id,)).fetchone()
        if row:
            return dict(row)
        cur = db.execute(
            "INSERT INTO threads(title, kind, parent_id, created_at) VALUES('Questions','side',?,?)",
            (main_id, _now()))
        return {"id": cur.lastrowid, "title": "Questions", "kind": "side",
                "timer_id": None, "parent_id": main_id}


def get_thread(thread_id: int) -> dict | None:
    with connect() as db:
        row = db.execute("SELECT * FROM threads WHERE id=?", (thread_id,)).fetchone()
        return dict(row) if row else None


def set_title(thread_id: int, title: str) -> None:
    with connect() as db:
        db.execute("UPDATE threads SET title=? WHERE id=?", (title, thread_id))


def list_messages(thread_id: int) -> list[dict]:
    with connect() as db:
        rows = db.execute(
            "SELECT role, kind, text, parts, attachment, label, created_at FROM messages WHERE thread_id=? ORDER BY id",
            (thread_id,),
        )
        return [dict(r) for r in rows]


def add_message(thread_id: int, role: str, text: str, *, parts: list | None = None,
                kind: str = "message", attachment: str | None = None, label: str | None = None) -> int:
    with connect() as db:
        cur = db.execute(
            "INSERT INTO messages(thread_id, role, kind, text, parts, attachment, label, created_at) VALUES(?,?,?,?,?,?,?,?)",
            (thread_id, role, kind, text, json.dumps(parts, ensure_ascii=False) if parts else None,
             attachment, label, _now()),
        )
        # First user message titles a chat thread.
        if role == "user" and kind == "message":
            db.execute(
                "UPDATE threads SET title=? WHERE id=? AND title='' AND kind='chat'",
                (text[:60], thread_id))
        return cur.lastrowid


def add_request(thread_id: int, task: str, mode: str, max_seconds: int | None, instructions: str) -> int:
    with connect() as db:
        # A new request supersedes any pending one on the thread.
        db.execute(
            "UPDATE recording_requests SET status='cancelled' WHERE thread_id=? AND status='pending'",
            (thread_id,))
        cur = db.execute(
            "INSERT INTO recording_requests(thread_id, task, mode, max_seconds, instructions, created_at) VALUES(?,?,?,?,?,?)",
            (thread_id, task, mode, max_seconds, instructions, _now()))
        return cur.lastrowid


def pending_request(thread_id: int) -> dict | None:
    with connect() as db:
        row = db.execute(
            "SELECT * FROM recording_requests WHERE thread_id=? AND status='pending' ORDER BY id DESC LIMIT 1",
            (thread_id,)).fetchone()
        return dict(row) if row else None


def resolve_request(request_id: int, status: str = "answered") -> None:
    with connect() as db:
        db.execute("UPDATE recording_requests SET status=? WHERE id=?", (status, request_id))


def has_user_input(thread_id: int) -> bool:
    """True once the learner sent a message or a take, in the thread or its side."""
    with connect() as db:
        return db.execute(
            "SELECT 1 FROM messages WHERE role='user' AND kind IN ('message','audio') "
            "AND (thread_id=? OR thread_id IN (SELECT id FROM threads WHERE parent_id=?)) LIMIT 1",
            (thread_id, thread_id)).fetchone() is not None


def delete_thread(thread_id: int) -> None:
    """Drop a thread and its side thread completely: messages, requests, timer."""
    with write() as db:
        tids = [r["id"] for r in db.execute(
            "SELECT id FROM threads WHERE id=? OR parent_id=?", (thread_id, thread_id))]
        marks = ",".join("?" * len(tids))
        timer_id = db.execute(
            "SELECT timer_id FROM threads WHERE id=?", (thread_id,)).fetchone()["timer_id"]
        db.execute(f"DELETE FROM messages WHERE thread_id IN ({marks})", tids)
        db.execute(f"DELETE FROM recording_requests WHERE thread_id IN ({marks})", tids)
        db.execute(f"DELETE FROM threads WHERE id IN ({marks})", tids)
        if timer_id:
            db.execute("DELETE FROM timer_periods WHERE session_id=?", (timer_id,))
            db.execute("DELETE FROM timer_sessions WHERE id=?", (timer_id,))
