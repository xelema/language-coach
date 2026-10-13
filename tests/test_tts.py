"""Click-to-listen TTS: Cartesia is called once per (text, speed), then cached."""
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

os.environ["LC_DATA_DIR"] = tempfile.mkdtemp()

from app import auth  # noqa: E402

os.environ["LC_PASSWORD_HASH"] = auth.make_hash("testpw")

from fastapi.testclient import TestClient  # noqa: E402

from app import db, notebook  # noqa: E402
from app.main import app  # noqa: E402

MP3 = b"ID3fake-mp3"
JA_VOICE = {"data": [{"id": "ja-voice-1", "status": "active", "gender": "feminine",
                      "name": "Aoi", "description": ""}]}


class TtsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.environ["LC_DATA_DIR"] = self.tmp.name
        os.environ["CARTESIA_API_KEY"] = "test-key"
        self.addCleanup(os.environ.pop, "CARTESIA_API_KEY", None)
        auth._attempts.clear()
        self.new_notebook("ko")
        self.client = TestClient(app)
        self.client.post("/login", json={"password": "testpw"})
        post = patch("app.tts.httpx.post", return_value=MagicMock(status_code=200, content=MP3))
        self.post = post.start()
        self.addCleanup(post.stop)

    def new_notebook(self, code):
        """Le carnet porte la langue : c'est lui qui décide ce qui est audible."""
        with db.write() as conn:
            notebook.insert_version(
                conn, notebook.new_notebook(code, {"objective": "Test", "level": "A1"}))

    def get(self, text="감사합니다", speed="normal"):
        return self.client.get("/api/tts", params={"text": text, "speed": speed})

    def test_synthesizes_once_then_serves_cache(self):
        first, again = self.get(), self.get("  감사합니다 ")
        self.assertEqual((first.status_code, first.content), (200, MP3))
        self.assertEqual(again.content, MP3)
        self.assertEqual(self.post.call_count, 1)
        body = self.post.call_args.kwargs["json"]
        self.assertEqual((body["transcript"], body["generation_config"]["speed"]), ("감사합니다", 1.0))

    def test_slow_is_a_separate_clip(self):
        self.get()
        self.get(speed="lent")
        self.assertEqual(self.post.call_count, 2)
        self.assertEqual(self.post.call_args.kwargs["json"]["generation_config"]["speed"], 0.6)

    def test_rejects_without_spending(self):
        for text, speed in [("hello", "normal"), ("", "normal"), ("가" * 201, "normal"), ("감사", "x2")]:
            self.assertEqual(self.get(text, speed).status_code, 400, (text[:5], speed))
        os.environ.pop("CARTESIA_API_KEY")
        self.assertEqual(self.get().status_code, 503)
        self.post.return_value = MagicMock(status_code=402, text="quota")
        os.environ["CARTESIA_API_KEY"] = "k"
        self.assertEqual(self.get().status_code, 503)
        self.assertEqual(self.post.call_count, 1)

    def test_requires_login(self):
        self.assertEqual(TestClient(app).get("/api/tts", params={"text": "안녕"}).status_code, 401)

    def test_script_of_another_language_is_refused(self):
        """Un carnet coréen n'accepte pas de texte japonais : la langue du carnet
        décide de ce qui est synthétisable."""
        self.assertEqual(self.get("ありがとう").status_code, 400)
        self.assertEqual(self.post.call_count, 0)

    def test_japanese_notebook_speaks_japanese(self):
        self.new_notebook("ja")
        get = patch("app.tts.httpx.get", return_value=MagicMock(status_code=200, json=lambda: JA_VOICE))
        get.start()
        self.addCleanup(get.stop)
        res = self.client.get("/api/tts", params={"text": "ありがとう", "speed": "normal"})
        self.assertEqual(res.status_code, 200)
        body = self.post.call_args.kwargs["json"]
        self.assertEqual((body["language"], body["voice"]), ("ja", "ja-voice-1"))


if __name__ == "__main__":
    unittest.main()
