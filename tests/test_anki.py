"""Covers the vendored Anki export: package list, GUID stability, downloads."""
import io
import os
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

from app import anki, auth, coach, db, notebook

os.environ["LC_PASSWORD_HASH"] = auth.make_hash("testpw")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def initial():
    return {"version": 1, "language": "ko", "calibration": [], "resources": [], "profile": {"objective": "Test", "level": "A1"}, "start": "2026-09-07", "target": "2026-12-07",
            "next": "Diagnostic", "resume": None, "sessions": [], "cards": [],
            "reviews": [], "recordings": [], "checkpoints": []}


CARDS = [
    {"id": "c1", "introduced": "2026-09-08", "prompt": "Un film ?", "answer": "영화",
     "register": "neutre", "skill": "ecrit", "source": "Test"},
    {"id": "c2", "introduced": "2026-09-08", "prompt": "Manger ?", "answer": "먹어",
     "register": "familier", "skill": "oral", "source": "Test"},
    {"id": "c3", "introduced": "2026-09-10", "prompt": "Écoute", "answer": "듣기",
     "register": "neutre", "skill": "ecoute", "source": "Test"},
]


def seed(state):
    with db.write() as conn:
        notebook.insert_version(conn, state)


def apkg_guids(path):
    with zipfile.ZipFile(path) as z:
        data = z.read("collection.anki2")
    col = Path(tempfile.mkdtemp()) / "collection.anki2"
    col.write_bytes(data)
    conn = sqlite3.connect(col)
    try:
        return {row[0] for row in conn.execute("SELECT guid FROM notes")}
    finally:
        conn.close()


class AnkiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.environ["LC_DATA_DIR"] = self.tmp.name
        state = initial()
        state["cards"] = [{**c, "level": 0, "due": "2026-09-09"} for c in CARDS]
        seed(state)

    def test_package_list_skips_audio_only_days(self):
        pkgs = anki.package_list(notebook.load())
        self.assertEqual([(p["name"], p["count"]) for p in pkgs],
                         [("ko-tout.apkg", 2), ("ko-2026-09-08.apkg", 2)])

    def test_guids_stable_across_rebuilds(self):
        state = notebook.load()
        path, count = anki.build(state, "ko-tout.apkg")
        self.assertEqual(count, 2)
        import genanki
        expected = {genanki.guid_for("ko-apprenant::" + c["id"])
                    for c in CARDS if c["skill"] != "ecoute"}
        self.assertEqual(apkg_guids(path), expected)
        # Rebuilding after a text fix keeps the same GUIDs (note update, no dupe).
        state["cards"][0]["answer"] = "영화 봤어."
        path2, _ = anki.build(state, "ko-tout.apkg")
        self.assertEqual(apkg_guids(path2), expected)

    def test_download_endpoints(self):
        c = TestClient(app)
        c.post("/login", json={"password": "testpw"})
        names = [p["name"] for p in c.get("/api/anki").json()]
        self.assertEqual(names, ["ko-tout.apkg", "ko-2026-09-08.apkg"])
        res = c.get("/api/anki/ko-tout.apkg")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(zipfile.is_zipfile(io.BytesIO(res.content)))
        self.assertEqual(c.get("/api/anki/ko-2026-09-10.apkg").status_code, 404)
        self.assertEqual(c.get("/api/anki/..%2Fcoach.db").status_code, 404)
        self.assertEqual(c.get("/api/anki/ko-2026-13-99.apkg").status_code, 404)

    def test_save_progress_chip_links_day_package(self):
        _result, label = coach._save_progress({}, {"cards": [dict(CARDS[0], id="c9", introduced="2026-09-11")]})
        self.assertIn("1 carte ajoutée", label)
        self.assertIn("⬇ ko-2026-09-11.apkg", label)


if __name__ == "__main__":
    unittest.main()
