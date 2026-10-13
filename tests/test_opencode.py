"""Covers the Gemini wire <-> OpenAI translation in app/opencode.py and the
/api/settings round-trip."""
import json
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ["LC_DATA_DIR"] = tempfile.mkdtemp()

from app import auth, opencode, settings  # noqa: E402

os.environ["LC_PASSWORD_HASH"] = auth.make_hash("testpw")

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


class MessagesTest(unittest.TestCase):
    def test_tool_call_roundtrip(self):
        contents = [
            {"role": "user", "parts": [{"text": "bonjour"}]},
            {"role": "model", "parts": [
                {"text": "je lance"},
                {"thoughtSignature": "abc"},
                {"text": "raisonnement cache", "thought": True},
                {"functionCall": {"name": "save_progress", "args": {"next": "rev"}}},
                {"functionCall": {"name": "set_channels", "args": {"ecoute": True}}}]},
            {"role": "user", "parts": [
                {"functionResponse": {"name": "save_progress", "response": {"ok": True}}},
                {"functionResponse": {"name": "set_channels", "response": {"ok": True}}}]},
            {"role": "user", "parts": [
                {"text": "et ?"},
                {"inlineData": {"mimeType": "audio/webm", "data": "AA=="}}]},
        ]
        msgs = opencode._messages(contents, "sys")
        self.assertEqual(msgs[0], {"role": "system", "content": "sys"})
        self.assertEqual(msgs[1], {"role": "user", "content": "bonjour"})
        model = msgs[2]
        self.assertEqual(model["role"], "assistant")
        self.assertEqual(model["content"], "je lance")
        ids = [tc["id"] for tc in model["tool_calls"]]
        self.assertEqual([tc["function"]["name"] for tc in model["tool_calls"]],
                         ["save_progress", "set_channels"])
        self.assertEqual(json.loads(model["tool_calls"][0]["function"]["arguments"]),
                         {"next": "rev"})
        self.assertEqual([(m["role"], m["tool_call_id"]) for m in msgs[3:5]],
                         [("tool", ids[0]), ("tool", ids[1])])
        self.assertEqual(json.loads(msgs[3]["content"]), {"ok": True})
        # L'audio devient un marqueur texte : jamais d'illusion d'ecoute.
        self.assertEqual(msgs[5]["role"], "user")
        self.assertIn("non audible", msgs[5]["content"])

    def test_schema_drops_nullable(self):
        tool = {"name": "t", "description": "",
                "parameters": {"type": "object",
                               "properties": {"x": {"type": "string", "nullable": True}}}}
        self.assertEqual(opencode._schema(tool),
                         {"name": "t", "description": "",
                          "parameters": {"type": "object",
                                         "properties": {"x": {"type": "string"}}}})


class GenerateTurnTest(unittest.TestCase):
    def test_deltas_assemble_to_parts(self):
        chunks = iter([
            {"choices": [{"delta": {"content": "안"}}]},
            {"choices": [{"delta": {"content": "녕"}}]},
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "id": "c1",
                 "function": {"name": "save_progress", "arguments": '{"a":'}}]}}]},
            {"choices": [{"delta": {"tool_calls": [
                {"index": 0, "function": {"arguments": "1}"}}]}}]},
        ])
        seen = []
        with patch("app.opencode._stream", return_value=chunks):
            parts = opencode.generate_turn(
                [{"role": "user", "parts": [{"text": "hi"}]}], on_text=seen.append)
        self.assertEqual(seen, ["안", "녕"])
        self.assertEqual(parts, [{"text": "안녕"},
                                 {"functionCall": {"name": "save_progress", "args": {"a": 1}}}])


class SettingsApiTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.saved = {k: os.environ.get(k) for k in ("LC_DATA_DIR", "LC_PROVIDER", "LC_MODEL")}
        os.environ["LC_DATA_DIR"] = self.tmp
        os.environ.pop("LC_PROVIDER", None)
        os.environ.pop("LC_MODEL", None)
        auth._attempts.clear()
        self.addCleanup(self._restore)

    def _restore(self):
        for k, v in self.saved.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v

    def test_pick_provider_and_model_via_api(self):
        c = TestClient(app)
        self.assertEqual(c.post("/login", json={"password": "testpw"}).status_code, 200)
        with patch("app.main.opencode.models",
                   return_value=["deepseek-v4.1-flash", "glm-5.3-flash"]):
            res = c.post("/api/settings",
                         json={"provider": "opencode", "model": "glm-5.3-flash"})
            self.assertEqual(res.status_code, 200, res.text)
            body = c.get("/api/settings").json()
        self.assertEqual(body["provider"], "opencode")
        self.assertEqual(body["model"], "glm-5.3-flash")
        self.assertIn("deepseek-v4.1-flash", body["models"]["opencode"])
        # Persisted on disk, per provider.
        self.assertEqual(settings.load(),
                         {"provider": "opencode", "models": {"opencode": "glm-5.3-flash"}})
        self.assertEqual(settings.current_model(), "glm-5.3-flash")

    def test_env_fallback_and_bad_provider(self):
        c = TestClient(app)
        c.post("/login", json={"password": "testpw"})
        self.assertEqual(settings.current_provider(), "gemini")
        self.assertEqual(settings.current_model(), "gemini-3.8-flash-tiered")
        os.environ["LC_PROVIDER"] = "opencode"
        os.environ["LC_MODEL"] = "env-model"
        self.assertEqual(settings.current_provider(), "opencode")
        self.assertEqual(settings.current_model(), "env-model")
        self.assertEqual(c.post("/api/settings", json={"provider": "wat"}).status_code, 400)


if __name__ == "__main__":
    unittest.main()
