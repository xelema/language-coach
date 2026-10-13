"""Voice takes: dictaphone import, archived-take replay, hear_recording tool."""
import io
import json
import os
import tempfile
import unittest
import wave
from unittest.mock import patch

os.environ["LC_DATA_DIR"] = tempfile.mkdtemp()

from app import auth  # noqa: E402

os.environ["LC_PASSWORD_HASH"] = auth.make_hash("testpw")

from fastapi.testclient import TestClient  # noqa: E402

from app import coach, db, notebook  # noqa: E402
from app.main import app  # noqa: E402


def wav_bytes(seconds=0.1):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(8000)
        w.writeframes(b"\x00\x01" * int(8000 * seconds))
    return buf.getvalue()


def initial(recordings=()):
    return {"version": 1, "language": "ko", "calibration": [], "profile": {"objective": "Test", "level": "A1"}, "start": "2026-09-20", "target": "2026-12-07",
            "next": "Dire une action d'hier", "resume": None, "sessions": [],
            "cards": [], "reviews": [], "recordings": list(recordings), "checkpoints": [],
            "review_engine": "anki"}


def text_turn(text):
    def gen(contents, system=None, tools=None, on_text=None):
        text_turn.contents.append(contents)
        if on_text:
            on_text(text)
        return [{"text": text}]
    return gen


def call_turn(name, args):
    def gen(contents, system=None, tools=None, on_text=None):
        text_turn.contents.append(contents)
        return [{"functionCall": {"name": name, "args": args}}]
    return gen


def events(res):
    return [json.loads(line) for line in res.text.splitlines() if line.strip()]


class RecordingsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.environ["LC_DATA_DIR"] = self.tmp.name
        text_turn.contents = []
        self.client = TestClient(app)
        auth._attempts.clear()
        self.client.post("/login", json={"password": "testpw"})
        self.audio = wav_bytes()
        root = notebook.audio_root() / "enregistrements"
        root.mkdir(parents=True)
        (root / "2026-09-08_journee_spontane_abc123.mp3").write_bytes(self.audio)
        self.recording = {"id": "abc123", "date": "2026-09-08", "task": "journee",
                          "mode": "spontane", "path": "enregistrements/2026-09-08_journee_spontane_abc123.mp3",
                          "note": "première prise", "seconds": 60.0,
                          "sha256": notebook.fingerprint(root / "2026-09-08_journee_spontane_abc123.mp3")}
        with db.write() as conn:
            notebook.insert_version(conn, initial([self.recording]))

    def import_file(self, data=None, name="dictaphone.wav", **headers):
        heads = {"X-Audio-Name": name, "X-Audio-Task": "journee", "X-Audio-Mode": "spontane",
                 "X-Audio-Date": "2026-09-24", **headers}
        return self.client.post("/api/recordings/import", headers=heads,
                                content=data if data is not None else self.audio)

    def test_import_registers_with_sha256(self):
        res = self.import_file()
        self.assertEqual(res.status_code, 200, res.text)
        entry = res.json()
        self.assertEqual(entry["task"], "journee")
        state = notebook.load()
        stored = state["recordings"][-1]
        self.assertEqual(stored["sha256"], notebook.fingerprint(
            notebook.audio_root() / stored["path"]))
        self.assertTrue(stored["path"].startswith("enregistrements/2026-09-24_journee_spontane_"))

    def test_import_dedup(self):
        self.import_file()
        res = self.import_file()
        self.assertTrue(res.json()["duplicate"])
        self.assertEqual(len(notebook.load()["recordings"]), 2)

    def test_import_rejects_bad_magic_and_task(self):
        self.assertEqual(self.import_file(data=b"not audio").status_code, 400)
        self.assertEqual(self.import_file(**{"X-Audio-Task": "danse"}).status_code, 400)
        self.assertEqual(self.import_file(name="x.exe").status_code, 400)
        self.assertEqual(len(notebook.load()["recordings"]), 1)

    def test_list_recordings(self):
        res = self.client.get("/api/recordings")
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()[0]["id"], "abc123")
        self.assertFalse(res.json()[0]["missing"])

    def test_replay_does_not_register_or_resolve(self):
        tid = self.client.post("/api/threads").json()["id"]
        db.add_request(tid, "journee", "spontane", 60, "redis ta journée")
        with patch("app.main.gemini.has_token", return_value=True), patch(
            "app.coach.gemini.generate_turn", side_effect=text_turn("Réécouté.")
        ):
            evs = events(self.client.post(f"/api/threads/{tid}/turn",
                                          json={"event": "message", "audio": self.recording["path"]}))
        self.assertEqual(evs[-1]["type"], "done")
        self.assertEqual(len(notebook.load()["recordings"]), 1)
        self.assertIsNotNone(db.pending_request(tid))
        wire = json.loads(db.list_messages(tid)[-2]["parts"])
        self.assertIn("prise archivée", wire[0]["text"])
        # The archived audio rides inline so the model hears it again.
        self.assertTrue(any("inlineData" in p for p in text_turn.contents[-1][-1]["parts"]))

    def test_hear_recording_attaches_audio(self):
        with patch("app.main.gemini.has_token", return_value=True):
            tid = self.client.post("/api/session").json()["id"]
        turns = iter([call_turn("hear_recording", {"id": "abc123"}), text_turn("Réécouté.")])
        with patch("app.main.gemini.has_token", return_value=True), patch(
            "app.coach.gemini.generate_turn", side_effect=lambda *a, **k: next(turns)(*a, **k)
        ):
            evs = events(self.client.post(f"/api/threads/{tid}/turn",
                                          json={"event": "message", "text": "réécoute ma prise J1"}))
        self.assertTrue(any(e["type"] == "tool" and "réécoute" in e["label"] for e in evs))
        parts = text_turn.contents[-1][-1]["parts"]
        self.assertEqual(parts[0]["functionResponse"]["name"], "hear_recording")
        self.assertEqual(parts[1]["inlineData"]["mimeType"], "audio/mpeg")

    def test_hear_recording_unknown_id(self):
        result, label, path = coach._hear_recording({"id": "nope"})
        self.assertFalse(result["ok"])
        self.assertIsNone(path)


if __name__ == "__main__":
    unittest.main()
