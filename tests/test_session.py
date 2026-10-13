"""End-to-end session loop on test data, Gemini mocked at the stream boundary."""
import json
import os
import tempfile
import threading
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
    """A fake model turn that streams `text` then returns the parts verbatim."""
    def gen(contents, system=None, tools=None, on_text=None):
        text_turn.systems.append(system)
        if on_text:
            on_text(text)
        return [{"text": text}]
    return gen


def call_turn(name, args):
    def gen(contents, system=None, tools=None, on_text=None):
        return [{"functionCall": {"name": name, "args": args}}]
    return gen


def events(res):
    return [json.loads(line) for line in res.text.splitlines() if line.strip()]


class SessionFlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.environ["LC_DATA_DIR"] = self.tmp.name
        text_turn.systems = []
        self.client = TestClient(app)
        auth._attempts.clear()
        self.client.post("/login", json={"password": "testpw"})
        with db.write() as conn:
            notebook.insert_version(conn, initial())

    def stream(self, tid, body):
        return events(self.client.post(f"/api/threads/{tid}/turn", json=body))

    def test_full_session(self):
        with patch("app.main.gemini.has_token", return_value=True):
            res = self.client.post("/api/session")
        tid, timer_id = res.json()["id"], None
        self.assertTrue(res.json()["created"])
        thread = db.get_thread(tid)
        timer_id = thread["timer_id"]
        self.assertTrue(timer_id)
        self.assertEqual(thread["kind"], "session")
        self.assertFalse(timer.get(timer_id)["stopped"])
        self.assertEqual(db.list_messages(tid)[0]["kind"], "event")  # kickoff

        # Reopening while active returns the same session.
        res = self.client.post("/api/session")
        self.assertEqual(res.json()["id"], tid)
        self.assertFalse(res.json()["created"])

        opening = "Aujourd'hui : parler de ses goûts. Premier essai. [tâche: un goût]"
        with patch("app.main.gemini.has_token", return_value=True), patch(
            "app.coach.gemini.generate_turn", side_effect=text_turn(opening)
        ):
            evs = self.stream(tid, {"event": "start"})
        self.assertEqual([e["text"] for e in evs if e["type"] == "text"], [opening])
        self.assertEqual(evs[-1]["type"], "done")
        # The marker named the learner window and was stripped from the display text.
        msgs = db.list_messages(tid)
        self.assertEqual(msgs[-1]["text"], "Aujourd'hui : parler de ses goûts. Premier essai.")
        s = timer.get(timer_id)
        self.assertEqual(s["periods"][-1]["kind"], "learner")
        self.assertEqual(s["periods"][-1]["task"], "un goût")
        self.assertIn("Statut du carnet", text_turn.systems[-1])

        # The learner answers: coach period opens, meta line rides on the wire only.
        with patch("app.main.gemini.has_token", return_value=True), patch(
            "app.coach.gemini.generate_turn", side_effect=text_turn("Bien. Et en poli ?")
        ):
            evs = self.stream(tid, {"event": "message", "text": "영화 좋아해"})
        user = db.list_messages(tid)[-2]
        self.assertEqual(user["text"], "영화 좋아해")
        self.assertIn("[méta", json.loads(user["parts"])[0]["text"])
        s = timer.get(timer_id)
        self.assertEqual(s["periods"][-1]["kind"], "learner")

        # Finish: the coach calls save_progress, then delivers its recap.
        patch_session = {"session": {"id": "2026-09-24-seance-1", "date": "2026-09-24",
                                     "kind": "apprentissage", "summary": "goûts travaillés",
                                     "evidence": "chrono automatique", "completed": True,
                                     "completion_evidence": "critères vérifiés"},
                         "next": "Raconter hier", "prep": "Préparer passé composé simple.",
                         "resume": None}
        turns = iter([call_turn("save_progress", patch_session), text_turn("Récap. À demain.")])
        with patch("app.main.gemini.has_token", return_value=True), patch(
            "app.coach.gemini.generate_turn",
            side_effect=lambda *a, **k: next(turns)(*a, **k),
        ):
            evs = self.stream(tid, {"event": "finish"})
        self.assertTrue(any(e["type"] == "tool" and "séance enregistrée" in e["label"] for e in evs))
        state = notebook.load()
        saved = state["sessions"][-1]
        self.assertEqual(saved["timer_id"], timer_id)
        self.assertIn("timing", saved)
        self.assertTrue(saved["minutes"] >= 1)
        self.assertEqual(state["prep"], "Préparer passé composé simple.")
        self.assertTrue(timer.get(timer_id)["stopped"])
        self.assertTrue(coach.session_closed(db.get_thread(tid)))

        # A closed session refuses further turns.
        res = self.client.post(f"/api/threads/{tid}/turn",
                               json={"event": "message", "text": "encore ?"})
        self.assertEqual(res.status_code, 409)

    def test_finish_without_input_discards_the_session(self):
        res = self.client.post("/api/session")
        tid = res.json()["id"]
        timer_id = db.get_thread(tid)["timer_id"]
        side = self.client.get(f"/api/threads/{tid}/side").json()
        with patch("app.main.gemini.has_token", return_value=True), patch(
            "app.coach.gemini.generate_turn", side_effect=text_turn("Dis bonjour. [tâche: bonjour]")
        ):
            self.stream(tid, {"event": "start"})
        evs = self.stream(tid, {"event": "finish"})
        self.assertEqual(evs, [{"type": "discarded"}])
        self.assertIsNone(db.get_thread(tid))
        self.assertIsNone(db.get_thread(side["id"]))
        self.assertIsNone(timer.get(timer_id))
        self.assertEqual(db.list_messages(tid), [])
        self.assertEqual(notebook.load()["sessions"], [])
        self.assertNotIn(tid, [t["id"] for t in self.client.get("/api/threads").json()])

    def test_side_question_counts_as_input(self):
        tid = self.client.post("/api/session").json()["id"]
        self.assertFalse(db.has_user_input(tid))
        side = self.client.get(f"/api/threads/{tid}/side").json()
        db.add_message(side["id"], "user", "c'est quoi ?")
        self.assertTrue(db.has_user_input(tid))

    def test_failed_save_leaves_timer_running(self):
        res = self.client.post("/api/session")
        thread = db.get_thread(res.json()["id"])
        bad = {"session": {"id": "s1", "kind": "complete",
                           "summary": "x", "evidence": "y"}}
        result, label = coach._save_progress(thread, bad)
        self.assertFalse(result["ok"])
        self.assertIn("date", result["error"])  # named field, not a bare KeyError
        self.assertIn("erreur", label)
        self.assertFalse(timer.get(thread["timer_id"])["stopped"])

        # A corrected retry still saves and stops the timer.
        good = {"session": {"id": "s1", "date": "2026-09-24", "kind": "apprentissage",
                            "summary": "x", "evidence": "y", "completed": False}}
        result, _ = coach._save_progress(thread, good)
        self.assertTrue(result["ok"])
        saved = notebook.load()["sessions"][-1]
        self.assertEqual(saved["timer_id"], thread["timer_id"])
        self.assertTrue(timer.get(thread["timer_id"])["stopped"])

    def test_channels(self):
        # Declared at creation: stored on the thread, echoed back, injected into the prompt.
        res = self.client.post("/api/session", json={"ecoute": True, "parle": False})
        tid = res.json()["id"]
        self.assertEqual(res.json()["caps"], {"ecoute": True, "parle": False})
        self.assertEqual(json.loads(db.get_thread(tid)["caps"]), {"ecoute": True, "parle": False})
        with patch("app.main.gemini.has_token", return_value=True), patch(
            "app.coach.gemini.generate_turn", side_effect=text_turn("On reste à l'écrit.")
        ):
            self.stream(tid, {"event": "start"})
        self.assertIn("écoute possible", text_turn.systems[-1])
        self.assertIn("parole IMPOSSIBLE", text_turn.systems[-1])

        # A recording request is refused while parole is impossible.
        req = call_turn("request_recording",
                        {"task": "journee", "mode": "spontane", "instructions": "Dis bonjour"})
        turns = iter([req, text_turn("Pas de micro, on écrit.")])
        with patch("app.main.gemini.has_token", return_value=True), patch(
            "app.coach.gemini.generate_turn", side_effect=lambda *a, **k: next(turns)(*a, **k),
        ):
            evs = self.stream(tid, {"event": "message", "text": "ok"})
        self.assertTrue(any(e["type"] == "tool" and "pas pouvoir parler" in e["label"] for e in evs))
        self.assertIsNone(db.pending_request(tid))

        # The learner can finally speak: the coach flips the channel for the next turns.
        turns = iter([call_turn("set_channels", {"ecoute": True, "parle": True}),
                      text_turn("Allez, au micro.")])
        with patch("app.main.gemini.has_token", return_value=True), patch(
            "app.coach.gemini.generate_turn", side_effect=lambda *a, **k: next(turns)(*a, **k),
        ):
            evs = self.stream(tid, {"event": "message", "text": "finalement je peux parler"})
        self.assertTrue(any(e["type"] == "tool" and "canaux audio" in e["label"] for e in evs))
        self.assertEqual(json.loads(db.get_thread(tid)["caps"]), {"ecoute": True, "parle": True})

        # Reopening with a new declaration updates the same session instead of duplicating.
        res = self.client.post("/api/session", json={"ecoute": False, "parle": True})
        self.assertEqual(res.json()["id"], tid)
        self.assertFalse(res.json()["created"])
        self.assertEqual(res.json()["caps"], {"ecoute": False, "parle": True})

    def test_save_progress_schema_lists_required_fields(self):
        props = next(t for t in coach.coach_tools(coach.languages.get("ko"))
                     if t["name"] == "save_progress")["parameters"]["properties"]
        self.assertIn("date", props["session"]["required"])
        self.assertIn("apprentissage",
                      props["session"]["properties"]["kind"]["enum"])
        self.assertIn("prompt", props["cards"]["items"]["required"])
        # Les registres proposés sont ceux de la langue du carnet, pas une liste fixe.
        self.assertEqual(props["cards"]["items"]["properties"]["register"]["enum"],
                         list(coach.languages.get("ko").register_ids))
        self.assertIn("change", props["calibration"]["items"]["required"])

    def finish(self, felt=None, comment=None):
        """Une vraie séance (un message échangé) puis la clôture demandée."""
        tid = self.client.post("/api/session").json()["id"]
        with patch("app.main.gemini.has_token", return_value=True), patch(
            "app.coach.gemini.generate_turn", side_effect=text_turn("D'accord.")):
            self.client.post(f"/api/threads/{tid}/turn", json={"event": "message", "text": "bonjour"})
            body = {"event": "finish"}
            if felt is not None:
                body["felt"] = felt
            if comment is not None:
                body["comment"] = comment
            return tid, self.client.post(f"/api/threads/{tid}/turn", json=body)

    def test_finish_carries_the_declared_ressenti_into_the_closing_instruction(self):
        tid, res = self.finish("trop_facile", "un peu trop court")
        self.assertEqual(res.status_code, 200, res.text)
        instruction = self.closing_instruction(tid)
        self.assertIn("Ressenti déclaré", instruction)
        self.assertIn("trop facile", instruction)
        self.assertIn("un peu trop court", instruction)

    def test_finish_without_ressenti_asks_for_non_dit(self):
        tid, _ = self.finish()
        self.assertIn("non_dit", self.closing_instruction(tid))

    def test_unknown_ressenti_is_refused(self):
        _, res = self.finish("bof")
        self.assertEqual(res.status_code, 400)

    def test_calibration_chip_shows_its_content_in_the_thread(self):
        result, label = coach._save_progress({}, {"calibration": [{
            "id": "cal-1", "date": coach.today(), "felt": "trop_facile",
            "observation": "réponses immédiates, aucune hésitation",
            "change": "production plus longue et moins d'indices"}]})
        self.assertTrue(result["ok"], result)
        self.assertIn("trop facile", label)
        self.assertIn("production plus longue", label)

    def closing_instruction(self, tid):
        rows = [m for m in db.list_messages(tid) if m["kind"] == "event" and m["parts"]]
        return " ".join(json.loads(m["parts"])[0]["text"] for m in rows)

    def test_validation_error_goes_back_to_model(self):
        res = self.client.post("/api/session")
        tid = res.json()["id"]
        with patch("app.main.gemini.has_token", return_value=True), patch(
            "app.coach.gemini.generate_turn", side_effect=text_turn("On y va.")
        ):
            self.stream(tid, {"event": "message", "text": "prêt"})
        bad = {"session": {"id": "x", "date": "pas-une-date", "minutes": 0, "kind": "apprentissage",
                           "summary": "s", "evidence": "e"}}
        turns = iter([call_turn("save_progress", bad), text_turn("Je retente plus tard.")])
        with patch("app.main.gemini.has_token", return_value=True), patch(
            "app.coach.gemini.generate_turn",
            side_effect=lambda *a, **k: next(turns)(*a, **k),
        ):
            evs = self.stream(tid, {"event": "finish"})
        self.assertTrue(any(e["type"] == "tool" and "erreur" in e["label"] for e in evs))
        self.assertEqual(notebook.load()["sessions"], [])
        # The stored row keeps the readable label, so the error chip survives a reload.
        tool_rows = [m for m in db.list_messages(tid) if m["kind"] == "tool"]
        self.assertIn("erreur", tool_rows[-1]["label"])


class GenerateTest(unittest.TestCase):
    def test_chunks_arrive_before_turn_ends(self):
        release = threading.Event()

        def slow(contents, system=None, tools=None, on_text=None):
            on_text("안녕")
            release.wait(5)
            return [{"text": "안녕"}]

        with patch("app.coach.gemini.generate_turn", side_effect=slow):
            gen = coach._generate([], system=None, tools=None)
            self.assertEqual(next(gen), {"type": "text", "text": "안녕"})
            release.set()
            with self.assertRaises(StopIteration) as stop:
                next(gen)
        self.assertEqual(stop.exception.value, [{"text": "안녕"}])


if __name__ == "__main__":
    unittest.main()
