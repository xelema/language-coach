"""Ports the test_coach.py checks that cover the vendored functions. No real data."""
import json
import os
import tempfile
import unittest
from copy import deepcopy
from datetime import date
from pathlib import Path

from app import db, notebook


def rejected(action):
    try:
        action()
    except (ValueError, KeyError, TypeError):
        return
    raise AssertionError("L'entrée invalide a été acceptée")


def seed(state, timers=()):
    with db.write() as conn:
        notebook.insert_version(conn, state)
        for session in timers:
            notebook.put_timer_session(conn, session)


def initial(**overrides):
    state = {"version": 1, "language": "ko", "calibration": [], "resources": [], "profile": {"objective": "Test", "level": "A1"}, "start": "2026-09-07", "target": "2026-12-07",
             "next": "Diagnostic", "resume": None, "sessions": [], "cards": [],
             "reviews": [], "recordings": [], "checkpoints": []}
    state.update(overrides)
    return state


class NotebookTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.environ["LC_DATA_DIR"] = self.tmp.name

    def versions(self):
        return notebook.version_count(), notebook.load()

    def test_status_and_recap(self):
        seed(initial())
        state = notebook.load()
        self.assertEqual(notebook.daily_recap(state, date(2026, 9, 6)), [])
        self.assertEqual(notebook.status(state, date(2026, 9, 7))["jours_sans_trace"], [])
        self.assertEqual(notebook.daily_recap(state, date(2026, 9, 7))[0]["status"], "a_faire")
        self.assertEqual(notebook.status(state, date(2026, 9, 8))["jours_sans_trace"], ["2026-09-07"])
        self.assertEqual(notebook.daily_recap(state, date(2026, 12, 10))[-1]["date"], "2026-12-07")

    def test_apply_update_and_rejections(self):
        seed(initial())
        session = {"id": "s1", "date": "2026-09-07", "minutes": 45, "kind": "partielle",
                   "summary": "영화 봤어.", "evidence": "Tentative écrite observée", "errors": []}
        card = {"id": "c1", "introduced": "2026-09-07", "prompt": "Un film hier ?", "answer": "영화 봤어.",
                "register": "familier", "skill": "ecrit", "source": "Exercice original"}
        notebook.apply_update({"session": session, "cards": [card], "resume": "Reprendre ici"})
        state = notebook.load()
        self.assertEqual(state["cards"][0]["due"], "2026-09-08")
        self.assertEqual(state["resume"], "Reprendre ici")
        self.assertEqual(notebook.daily_recap(state, date(2026, 9, 8))[0]["status"], "partielle")
        complete = deepcopy(state)
        complete["sessions"][0]["minutes"] = 60
        self.assertEqual(notebook.daily_recap(complete, date(2026, 9, 8))[0]["status"], "complete")
        self.assertEqual(notebook.status(state, date(2026, 9, 9))["jours_sans_trace"], ["2026-09-08"])

        before = self.versions()
        rejected(lambda: notebook.apply_update({"session": session}))
        rejected(lambda: notebook.apply_update({"reviews": [{"id": "early", "card": "c1", "date": "2026-09-07", "rating": "reussi"}]}))
        rejected(lambda: notebook.apply_update({"session": {**session, "id": "bad", "minutes": float("nan")}}))
        rejected(lambda: notebook.apply_update({"unknown": "x"}))
        self.assertEqual(self.versions(), before)

    def test_review_schedule(self):
        seed(initial())
        card = {"id": "c1", "introduced": "2026-09-07", "prompt": "Un film hier ?", "answer": "영화 봤어.",
                "register": "familier", "skill": "ecrit", "source": "Exercice original"}
        notebook.apply_update({"cards": [card]})
        for ident, when, rating, due in [("r1", "2026-09-08", "reussi", "2026-09-09"),
                                          ("r2", "2026-09-09", "reussi", "2026-09-12"),
                                          ("r3", "2026-09-12", "aide", "2026-09-13")]:
            notebook.apply_update({"reviews": [{"id": ident, "card": "c1", "date": when, "rating": rating}]})
            self.assertEqual(notebook.load()["cards"][0]["due"], due)
        rejected(lambda: notebook.apply_update({"reviews": [{"id": "repeat", "card": "c1", "date": "2026-09-12", "rating": "reussi"}]}))
        self.assertEqual(notebook.status(notebook.load(), date(2026, 9, 12))["cartes_dues"], [])
        self.assertEqual(len(notebook.status(notebook.load(), date(2026, 9, 13))["cartes_dues"]), 1)

    def test_checkpoints_and_progress(self):
        seed(initial())
        checkpoint = {"id": "b1", "date": "2026-09-14", "scores": {s: 1 for s in notebook.SKILLS},
                      "evidence": {s: "Preuve observée" for s in notebook.SKILLS},
                      "independent": True, "unseen": True, "audio_assessed": True}
        rejected(lambda: notebook.apply_update({"checkpoint": {**checkpoint, "audio_assessed": False}}))
        missing = deepcopy(checkpoint)
        missing["evidence"].pop("oral")
        rejected(lambda: notebook.apply_update({"checkpoint": missing}))
        notebook.apply_update({"checkpoint": checkpoint})
        self.assertEqual(notebook.progress(notebook.load())[1:], (100, "Bronze"))
        coached = {**checkpoint, "id": "practice", "scores": {s: 4 for s in notebook.SKILLS}, "independent": False}
        notebook.apply_update({"checkpoint": coached})
        self.assertEqual(notebook.progress(notebook.load())[1:], (100, "Bronze"))
        lower = {**checkpoint, "id": "later", "date": "2026-09-21", "scores": {s: 0 for s in notebook.SKILLS}}
        notebook.apply_update({"checkpoint": lower, "resume": None, "next": "Réécouter demain"})
        self.assertEqual(notebook.progress(notebook.load())[1:], (100, "Bronze"))

    def test_anki_engine(self):
        seed(initial(start="2026-09-08", target="2026-12-08", review_engine="anki"))
        session = {"id": "short", "date": "2026-09-09", "minutes": 35,
                   "kind": "apprentissage", "summary": "Mission finie", "evidence": "Test",
                   "completed": True, "completion_evidence": "Tous les exercices et variante réussis"}
        notebook.apply_update({"session": session})
        self.assertEqual(notebook.daily_recap(notebook.load(), date(2026, 9, 9))[-1]["status"], "complete")
        notebook.apply_update({"session": {**session, "id": "unfinished", "date": "2026-09-11", "minutes": 75, "completed": False}})
        self.assertEqual(notebook.daily_recap(notebook.load(), date(2026, 9, 11))[-1]["status"], "partielle")
        rejected(lambda: notebook.apply_update({"session": {**session, "id": "missing-proof", "completion_evidence": ""}}))
        rejected(lambda: notebook.apply_update({"reviews": [{"id": "r1", "date": "2026-09-12", "card": "film", "rating": "reussi"}]}))
        provisional = {"id": "provisional", "date": "2026-09-09", "scores": {s: 4 for s in notebook.SKILLS},
                       "evidence": {s: "À reconfirmer" for s in notebook.SKILLS}, "independent": True,
                       "unseen": True, "audio_assessed": True, "provisional": True}
        notebook.apply_update({"checkpoint": provisional})
        self.assertEqual(notebook.progress(notebook.load())[1:], (0, "Placement"))
        card = {"id": "film", "introduced": "2026-09-09", "prompt": "Un film ?", "answer": "영화",
                "register": "neutre", "skill": "ecrit", "source": "Test"}
        notebook.apply_update({"cards": [card]})
        self.assertEqual(notebook.status(notebook.load(), date(2026, 9, 12))["cartes_dues"], [])

    def test_session_with_timer(self):
        stopped = {"id": "measured", "stopped": True, "periods": [
            {"kind": "coach", "task": "", "start": "2026-09-12T12:00:00+00:00", "end": "2026-09-12T12:35:00+00:00"}]}
        running = {"id": "running", "stopped": False, "periods": [
            {"kind": "coach", "task": "", "start": "2026-09-12T13:00:00+00:00", "end": None}]}
        seed(initial(), timers=[stopped, running])
        timed = {"id": "measured-session", "date": "2026-09-12", "minutes": 35,
                 "kind": "apprentissage", "summary": "Mission finie", "evidence": "Test", "timer_id": "measured"}
        rejected(lambda: notebook.apply_update({"session": timed}))  # Fenêtre >20 min à confirmer.
        rejected(lambda: notebook.apply_update({"session": {**timed, "timer_id": "running"}}))
        rejected(lambda: notebook.apply_update({"session": {**timed, "timer_id": "inconnu"}}))
        notebook.apply_update({"session": {**timed, "time_confirmation": "35 min déclarées par l'apprenant"}})
        saved = notebook.load()["sessions"][-1]
        self.assertTrue(saved["timing"]["stopped"])
        self.assertEqual(saved["timing"]["session_minutes"], 35)
        rejected(lambda: notebook.apply_update({"session": {**timed, "id": "duplicate-timer",
                                                "time_confirmation": "encore"}}))

    def test_audio_path_containment(self):
        root = Path(self.tmp.name) / "audio"
        rejected(lambda: notebook.audio_path(root, "../private.wav"))
        self.assertEqual(notebook.audio_path(root, "enregistrements/a.wav"), (root / "enregistrements/a.wav").resolve())

    def test_onboarding_builds_a_notebook_without_deadline(self):
        seed(notebook.new_notebook("ja", {"objective": "parler avec un ami", "level": "A0",
                                          "registers": ["poli"]}))
        loaded = notebook.load()
        self.assertEqual(loaded["language"], "ja")
        self.assertIsNone(loaded["target"])
        self.assertEqual(loaded["calibration"], [])
        info = notebook.status(loaded, date.fromisoformat(loaded["start"]))
        self.assertIsNone(info["jours_restants"])
        self.assertEqual(info["profil"]["objectif"], "parler avec un ami")
        self.assertEqual(info["langue"], "japonais")

    def test_onboarding_rejects_unknown_language_level_or_register(self):
        rejected(lambda: notebook.new_notebook("xx", {"objective": "o", "level": "A1"}))
        rejected(lambda: notebook.new_notebook("ja", {"objective": "o", "level": "C3"}))
        rejected(lambda: notebook.new_notebook("ja", {"objective": "", "level": "A1"}))
        rejected(lambda: notebook.new_notebook("ja", {"objective": "o", "level": "A1",
                                                      "registers": ["keigo"]}))

    def test_deadline_is_optional_and_reversible(self):
        seed(notebook.new_notebook("ko", {"objective": "o", "level": "A2"}, start="2026-09-07"))
        notebook.apply_update({"target": "2026-12-07"})
        self.assertEqual(notebook.status(notebook.load(), date(2026, 9, 7))["jours_restants"], 91)
        self.assertEqual(notebook.load()["target"], "2026-12-07")
        notebook.apply_update({"target": None})
        self.assertIsNone(notebook.load()["target"])
        rejected(lambda: notebook.apply_update({"target": "2026-09-06"}))

    def test_calibration_is_recorded_and_exposed_to_the_coach(self):
        seed(notebook.new_notebook("ko", {"objective": "o", "level": "A1"}, start="2026-09-07"))
        change = "production plus longue, moins d'indices"
        entry = {"id": "cal-1", "date": "2026-09-07", "felt": "trop_facile",
                 "observation": "quatre réponses sans hésitation", "change": change}
        notebook.apply_update({"calibration": [entry]})
        self.assertEqual(notebook.status(notebook.load(), date(2026, 9, 7))["calibrage"][0]["change"], change)
        rejected(lambda: notebook.apply_update({"calibration": [dict(entry, id="cal-2", felt="ok")]}))
        rejected(lambda: notebook.apply_update({"calibration": [dict(entry, id="cal-3", change="")]}))
        # Une clôture sans ressenti reste représentable, et la page progression
        # reçoit l'historique de calibrage dans son rapport.
        notebook.apply_update({"calibration": [dict(entry, id="cal-4", felt="non_dit")]})
        report = notebook.report_data(notebook.load(), date(2026, 9, 8))
        self.assertEqual([c["felt"] for c in report["calibrage"]][:1], ["non_dit"])
        self.assertEqual(report["ressources"], [])

    def test_profile_can_be_refined_later(self):
        seed(notebook.new_notebook("ko", {"objective": "o", "level": "A1"}, start="2026-09-07"))
        notebook.apply_update({"profile": {"objective": "passer un entretien", "level": "A1",
                                           "level_verified": "A2"}})
        self.assertEqual(notebook.load()["profile"]["level_verified"], "A2")
        rejected(lambda: notebook.apply_update({"profile": {"objective": "x", "level": "A1",
                                                            "extra": "nope"}}))


if __name__ == "__main__":
    unittest.main()
