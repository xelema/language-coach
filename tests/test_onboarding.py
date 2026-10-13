"""Mise en route : langue, profil, vidéos validées, recherche de ressources.

Ces tests couvrent ce qui n'existait pas dans le projet d'origine : pas d'import
d'un dossier existant, mais un carnet créé par les réponses de l'apprenant.
"""
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ["LC_DATA_DIR"] = tempfile.mkdtemp()

from app import auth  # noqa: E402

os.environ["LC_PASSWORD_HASH"] = auth.make_hash("testpw")

from fastapi.testclient import TestClient  # noqa: E402

from app import coach, notebook  # noqa: E402
from app.main import app  # noqa: E402

CANDIDATE = {"id": "abc123", "title": "Japanese listening practice with a story",
             "channel": "Japarrot", "duration": 381,
             "url": "https://www.youtube.com/watch?v=abc123", "views": 2517349}


class OnboardingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.environ["LC_DATA_DIR"] = self.tmp.name
        auth._attempts.clear()
        self.client = TestClient(app)
        self.client.post("/login", json={"password": "testpw"})

    def onboard(self, **overrides):
        body = {"language": "ja",
                "profile": {"name": "Alex", "objective": "parler avec une amie japonaise",
                            "level": "A1", "cadence": "3 séances par semaine", "context": "mangas",
                            "audio": {"ecoute": True, "parle": False}},
                "resources": [CANDIDATE]}
        body.update(overrides)
        return self.client.post("/api/onboarding", json=body)

    def test_page_needs_a_session(self):
        self.assertEqual(TestClient(app).get("/onboarding", follow_redirects=False).status_code, 302)
        self.assertEqual(self.client.get("/onboarding").status_code, 200)

    def test_onboarding_stores_language_profile_and_videos(self):
        res = self.onboard()
        self.assertEqual(res.status_code, 200, res.text)
        profile = self.client.get("/api/profile").json()
        self.assertEqual(profile["language"], "ja")
        self.assertTrue(profile["script"], "le motif d'écriture sert à repérer le texte audible")
        self.assertEqual(profile["profile"]["audio"], {"ecoute": True, "parle": False})
        self.assertIsNone(profile["deadline"], "aucune échéance n'est imposée par défaut")
        state = notebook.load()
        self.assertEqual(state["resources"][0]["title"], CANDIDATE["title"])
        # Le coach voit la vidéo validée et le profil dans son prompt.
        prompt = coach.system_prompt({"id": 1, "kind": "session"})
        self.assertIn("Japarrot", prompt)
        self.assertIn("parler avec une amie japonaise", prompt)

    def test_one_notebook_only(self):
        self.onboard()
        self.assertEqual(self.onboard(language="ko").status_code, 409)

    def test_invalid_input_leaves_no_notebook(self):
        self.assertEqual(self.onboard(language="de").status_code, 400)
        self.assertEqual(self.onboard(resources=[{"title": "", "url": "https://x"}]).status_code, 400)
        self.assertEqual(self.onboard(profile={"objective": "o", "level": "C3"}).status_code, 400)
        self.assertFalse(self.client.get("/api/profile").json()["onboarded"])

    def test_deadline_is_optional_and_can_be_removed(self):
        self.onboard(deadline="2027-01-15")
        self.assertEqual(self.client.get("/api/profile").json()["deadline"], "2027-01-15")
        self.assertIsNone(self.client.post("/api/profile", json={"deadline": ""}).json()["deadline"])

    def test_resource_search_degrades_cleanly_then_returns_real_candidates(self):
        with patch("app.resources.available", return_value=False):
            res = self.client.post("/api/resource-search", json={"language": "ja", "level": "A0"})
            self.assertEqual(res.status_code, 503)
            self.assertIn("yt-dlp", res.json()["detail"])
        with patch("app.resources._search", return_value=[CANDIDATE]):
            res = self.client.post("/api/resource-search", json={"language": "ja", "level": "A0"})
            self.assertEqual(res.status_code, 200)
            self.assertEqual(res.json()["candidates"][0]["title"], CANDIDATE["title"])
        self.assertEqual(self.client.post("/api/resource-search", json={"language": "de"}).status_code, 400)

    def test_profile_exposes_the_model_access_state(self):
        """L'interface s'en sert pour réclamer la connexion Google avant l'échec."""
        self.onboard()
        with patch("app.main.gemini.has_token", return_value=False):
            without = self.client.get("/api/profile").json()
            self.assertFalse(without["model_ready"])
            self.assertEqual((without["provider"], without["oauth_url"]), ("gemini", "/oauth/login"))
        with patch("app.main.gemini.has_token", return_value=True):
            self.assertTrue(self.client.get("/api/profile").json()["model_ready"])

    def test_onboarding_without_audio_still_works(self):
        """L'écoute et la parole se déclarent à chaque séance, pas à la création."""
        res = self.client.post("/api/onboarding", json={
            "language": "ko", "profile": {"objective": "lire des webtoons", "level": "A0"}})
        self.assertEqual(res.status_code, 200, res.text)
        self.assertIsNone(res.json()["profile"]["audio"])

    def test_audio_declared_at_onboarding_is_reused_by_the_next_session(self):
        self.onboard()
        session = self.client.post("/api/session").json()
        self.assertEqual(session["caps"], {"ecoute": True, "parle": False})


if __name__ == "__main__":
    unittest.main()
