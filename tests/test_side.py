"""Side thread: questions beside a live session, notes back into the lesson."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ["LC_DATA_DIR"] = tempfile.mkdtemp()

from app import auth  # noqa: E402

os.environ["LC_PASSWORD_HASH"] = auth.make_hash("testpw")

from fastapi.testclient import TestClient  # noqa: E402

from app import coach, db, notebook, timer  # noqa: E402
from app.main import app  # noqa: E402


def initial():
    return {"version": 1, "language": "ko", "calibration": [], "resources": [], "profile": {"objective": "Test", "level": "A1"}, "start": "2026-09-20", "target": "2026-12-07",
            "next": "Dire une action d'hier", "resume": None, "sessions": [],
            "cards": [], "reviews": [], "recordings": [], "checkpoints": [],
            "review_engine": "anki"}


def text_turn(text):
    def gen(contents, system=None, tools=None, on_text=None):
        text_turn.calls.append({"system": system, "tools": tools, "contents": contents})
        if on_text:
            on_text(text)
        return [{"text": text}]
    return gen


def events(res):
    return [json.loads(line) for line in res.text.splitlines() if line.strip()]


class SideThreadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.environ["LC_DATA_DIR"] = self.tmp.name
        text_turn.calls = []
        self.client = TestClient(app)
        auth._attempts.clear()
        self.client.post("/login", json={"password": "testpw"})
        with db.write() as conn:
            notebook.insert_version(conn, initial())
        self.tid = self.client.post("/api/session").json()["id"]
        self.timer_id = db.get_thread(self.tid)["timer_id"]

    def stream(self, tid, body):
        return events(self.client.post(f"/api/threads/{tid}/turn", json=body))

    def coach_opening(self):
        with patch("app.main.gemini.has_token", return_value=True), patch(
            "app.coach.gemini.generate_turn", side_effect=text_turn("Dis un goût. [tâche: un goût]")
        ):
            self.stream(self.tid, {"event": "start"})

    def test_side_thread_lifecycle(self):
        # Only sessions have a side thread.
        chat = self.client.post("/api/threads").json()
        self.assertEqual(self.client.get(f"/api/threads/{chat['id']}/side").status_code, 400)

        side = self.client.get(f"/api/threads/{self.tid}/side").json()
        self.assertEqual(side["kind"], "side")
        self.assertEqual(side["parent_id"], self.tid)
        # Idempotent, and hidden from the drawer list.
        self.assertEqual(self.client.get(f"/api/threads/{self.tid}/side").json()["id"], side["id"])
        self.assertNotIn(side["id"], [t["id"] for t in self.client.get("/api/threads").json()])

    def test_side_sees_lesson_and_leaves_timer_alone(self):
        self.coach_opening()
        side = self.client.get(f"/api/threads/{self.tid}/side").json()
        periods_before = timer.get(self.timer_id)["periods"]

        with patch("app.main.gemini.has_token", return_value=True), patch(
            "app.coach.gemini.generate_turn", side_effect=text_turn("Un indice.")
        ):
            evs = self.stream(side["id"], {"event": "message", "text": "c'est quoi la réponse ?"})
        self.assertEqual(evs[-1]["type"], "done")

        call = text_turn.calls[-1]
        self.assertIsNone(call["tools"])                      # never writes progress
        self.assertIn("lecture seule", call["system"])
        self.assertIn("Dis un goût", call["system"])          # lesson tail as context
        self.assertIn("un goût", call["system"])              # pending exercise named
        self.assertIn("indice", call["system"])               # hint, not the answer
        self.assertEqual(timer.get(self.timer_id)["periods"], periods_before)
        rows = db.list_messages(side["id"])
        self.assertEqual([(r["role"], r["text"]) for r in rows],
                         [("user", "c'est quoi la réponse ?"), ("model", "Un indice.")])

    def test_note_reaches_the_coach_thread(self):
        self.coach_opening()
        side = self.client.get(f"/api/threads/{self.tid}/side").json()
        res = self.client.post(f"/api/threads/{self.tid}/note",
                               json={"text": "il confond 은 et 는"})
        self.assertEqual(res.status_code, 200)
        row = db.list_messages(self.tid)[-1]
        self.assertEqual(row["kind"], "event")
        self.assertIn("il confond", row["label"])
        # The wire replays stored rows: the coach reads the note on its next turn.
        wire = coach.wire_contents(self.tid)
        self.assertIn("il confond 은 et 는", wire[-1]["parts"][0]["text"])
        self.assertEqual(side["kind"], "side")

    def test_closed_session_locks_the_side(self):
        self.coach_opening()
        side = self.client.get(f"/api/threads/{self.tid}/side").json()
        timer.stop(self.timer_id)
        notebook.apply_update({"session": {
            "id": "2026-09-24-seance-1", "date": "2026-09-24", "kind": "apprentissage",
            "summary": "s", "evidence": "e", "completed": True,
            "completion_evidence": "ce", "minutes": 10, "timer_id": self.timer_id}})
        with patch("app.main.gemini.has_token", return_value=True):
            res = self.client.post(f"/api/threads/{side['id']}/turn",
                                   json={"event": "message", "text": "encore ?"})
        self.assertEqual(res.status_code, 409)
        self.assertEqual(self.client.post(f"/api/threads/{self.tid}/note",
                                          json={"text": "trop tard"}).status_code, 409)


if __name__ == "__main__":
    unittest.main()
