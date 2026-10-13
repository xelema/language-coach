"""Progress dashboard: /api/progress payload and /progres page."""
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path

os.environ["LC_DATA_DIR"] = tempfile.mkdtemp()

from app import auth  # noqa: E402

os.environ["LC_PASSWORD_HASH"] = auth.make_hash("testpw")

from fastapi.testclient import TestClient  # noqa: E402

from app import db, notebook  # noqa: E402
from app.main import app  # noqa: E402

SESSION = {"id": "s1", "date": "2026-09-10", "minutes": 43, "kind": "apprentissage",
           "summary": "Séance complète.", "evidence": "43 min chronométrées.",
           "completed": True, "completion_evidence": "Critères vérifiés.",
           "errors": [{"attempt": "준아해", "correction": "좋아해", "why": "Voyelle ㅗ."}]}
CHECKPOINT = {"id": "b1", "date": "2026-09-08",
              "scores": {"ecoute": 1, "oral": 1, "ecrit": 1, "registre": 1},
              "evidence": {"ecoute": "x", "oral": "x", "ecrit": "x", "registre": "x"},
              "independent": True, "unseen": True, "audio_assessed": True,
              "provisional": True, "audit_note": "à reconfirmer"}
RECORDING = {"id": "r1", "date": "2026-09-10", "task": "conversation", "mode": "spontane",
             "path": "enregistrements/r1.mp3", "note": "", "seconds": 22.2}


def state(**over):
    s = {"version": 1, "language": "ko", "calibration": [], "resources": [], "profile": {"objective": "Test", "level": "A1"}, "start": "2026-09-07", "target": "2026-12-07", "next": "Diagnostic",
         "resume": None, "sessions": [], "cards": [], "reviews": [], "recordings": [],
         "checkpoints": [], "review_engine": "anki"}
    s.update(over)
    return s


class ReportDataTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.environ["LC_DATA_DIR"] = self.tmp.name

    def seed(self, s):
        with db.write() as conn:
            notebook.insert_version(conn, s)

    def test_payload_matches_notebook(self):
        self.seed(state(sessions=[SESSION], checkpoints=[CHECKPOINT], recordings=[RECORDING]))
        data = notebook.report_data(notebook.load(), date(2026, 9, 11))
        day = next(d for d in data["days"] if d["date"] == "2026-09-10")
        self.assertEqual((day["status"], day["minutes"]), ("complete", 43))
        self.assertEqual(data["lp"], 0)          # a provisional checkpoint earns no LP
        self.assertEqual(data["minutes_pratiquees"], 43)
        self.assertEqual(data["cartes_dues"], 0)  # anki engine: scheduling lives in AnkiDroid
        self.assertTrue(data["recordings"][0]["missing"])

    def test_recording_present_when_file_exists(self):
        self.seed(state(recordings=[RECORDING]))
        f = Path(self.tmp.name) / "audio" / "enregistrements" / "r1.mp3"
        f.parent.mkdir(parents=True)
        f.write_bytes(b"xx")
        data = notebook.report_data(notebook.load(), date(2026, 9, 10))
        self.assertFalse(data["recordings"][0]["missing"])


class ProgressEndpointTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.environ["LC_DATA_DIR"] = self.tmp.name
        auth._attempts.clear()

    def test_requires_login(self):
        c = TestClient(app)
        self.assertEqual(c.get("/api/progress").status_code, 401)
        self.assertEqual(c.get("/progres", follow_redirects=False).status_code, 302)

    def test_no_notebook_is_404(self):
        c = TestClient(app)
        self.assertEqual(c.post("/login", json={"password": "testpw"}).status_code, 200)
        self.assertEqual(c.get("/api/progress").status_code, 404)

    def test_page_and_payload(self):
        with db.write() as conn:
            notebook.insert_version(conn, state(sessions=[SESSION]))
        c = TestClient(app)
        self.assertEqual(c.post("/login", json={"password": "testpw"}).status_code, 200)
        self.assertEqual(c.get("/progres").status_code, 200)
        data = c.get("/api/progress").json()
        self.assertEqual(data["sessions"][0]["minutes"], 43)
        self.assertEqual(data["target"], "2026-12-07")


if __name__ == "__main__":
    unittest.main()
