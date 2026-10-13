"""Covers the auth guard and message persistence."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ["LC_DATA_DIR"] = tempfile.mkdtemp()

from app import auth  # noqa: E402

os.environ["LC_PASSWORD_HASH"] = auth.make_hash("testpw")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def logged_in(client: TestClient) -> None:
    res = client.post("/login", json={"password": "testpw"})
    assert res.status_code == 200, res.text


class AuthGuardTest(unittest.TestCase):
    def setUp(self):
        auth._attempts.clear()

    def test_api_requires_session(self):
        c = TestClient(app)
        self.assertEqual(c.get("/api/threads").status_code, 401)
        self.assertEqual(c.post("/api/threads").status_code, 401)
        self.assertEqual(c.post("/api/session").status_code, 401)
        self.assertEqual(c.post("/api/threads/1/turn", json={"event": "message", "text": "hi"}).status_code, 401)

    def test_manifest_is_public(self):
        c = TestClient(app)
        self.assertEqual(c.get("/static/manifest.json").status_code, 200)
        self.assertEqual(c.get("/static/icon-192.png").status_code, 200)
        self.assertEqual(c.get("/static/app.js", follow_redirects=False).status_code, 302)

    def test_page_redirects_to_login(self):
        self.assertEqual(TestClient(app).get("/", follow_redirects=False).status_code, 302)

    def test_wrong_password_rejected(self):
        self.assertEqual(TestClient(app).post("/login", json={"password": "nope"}).status_code, 401)

    def test_login_says_when_no_password_is_configured(self):
        """Sans hash côté serveur, un 401 ferait croire à une faute de frappe."""
        saved = os.environ.pop("LC_PASSWORD_HASH")
        self.addCleanup(os.environ.__setitem__, "LC_PASSWORD_HASH", saved)
        res = TestClient(app).post("/login", json={"password": "peu importe"})
        self.assertEqual(res.status_code, 503)
        self.assertIn("LC_PASSWORD_HASH", res.json()["detail"])

    def test_login_rate_limited(self):
        c = TestClient(app)
        for _ in range(auth.MAX_ATTEMPTS):
            c.post("/login", json={"password": "nope"})
        self.assertEqual(c.post("/login", json={"password": "testpw"}).status_code, 429)


class PersistenceTest(unittest.TestCase):
    def setUp(self):
        auth._attempts.clear()

    def test_messages_persist_after_stream(self):
        c = TestClient(app)
        logged_in(c)
        tid = c.post("/api/threads").json()["id"]

        def fake_turn(contents, system=None, tools=None, on_text=None):
            for chunk in ("안녕", "하세요"):
                if on_text:
                    on_text(chunk)
            return [{"text": "안녕하세요"}]

        with patch("app.main.gemini.has_token", return_value=True), patch(
            "app.main.gemini.generate_turn", side_effect=fake_turn
        ):
            res = c.post(f"/api/threads/{tid}/turn", json={"event": "message", "text": "bonjour"})
        self.assertEqual(res.status_code, 200)
        text = "".join(json.loads(line)["text"] for line in res.text.splitlines()
                       if line.strip() and json.loads(line)["type"] == "text")
        self.assertEqual(text, "안녕하세요")
        # A "reload" reads both rows back from SQLite.
        msgs = c.get(f"/api/threads/{tid}/messages").json()
        self.assertEqual([(m["role"], m["text"]) for m in msgs], [("user", "bonjour"), ("model", "안녕하세요")])


if __name__ == "__main__":
    unittest.main()
