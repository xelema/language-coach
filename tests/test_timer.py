"""Timer transitions on a fake clock, and save-with-timing through apply_update."""
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from app import db, notebook, timer  # noqa: E402

T0 = datetime(2026, 9, 24, 10, 0, 0, tzinfo=timezone.utc)


def at(minutes=0, seconds=0):
    return T0 + timedelta(minutes=minutes, seconds=seconds)


def kinds(session):
    return [(p["kind"], p["task"]) for p in session["periods"]]


class TimerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.environ["LC_DATA_DIR"] = self.tmp.name

    def test_exchange_flow(self):
        s = timer.start("s1", now=at(0))
        self.assertEqual(kinds(s), [("coach", "")])

        # First coach answer ends: a named learner window opens.
        s = timer.coach_stream_end("s1", "dire un goût", now=at(1))
        self.assertEqual(kinds(s), [("coach", ""), ("learner", "dire un goût")])

        # Florian answers after 40 s: coach period opens, no long-window flag.
        r = timer.user_message("s1", now=at(1, 40))
        self.assertEqual(r["returned_after_s"], 0)

        s = timer.coach_stream_end("s1", "", now=at(2, 30))
        self.assertEqual(kinds(s)[-1], ("learner", "réponse"))  # fallback label

        summary = timer.summary("s1", now=at(3))
        self.assertEqual(summary["state"], "learner")
        self.assertFalse(summary["needs_confirmation"])
        self.assertEqual(len(summary["responses"]), 2)

    def test_pause_resume_and_long_return(self):
        timer.start("s1", now=at(0))
        timer.coach_stream_end("s1", "lire à voix haute", now=at(5))
        timer.pause("s1", now=at(6))
        s = timer.summary("s1", now=at(8))
        self.assertEqual(s["state"], "pause")
        timer.resume("s1", now=at(26))
        s = timer.get("s1")
        self.assertEqual(kinds(s)[-1], ("learner", "lire à voix haute"))  # back on task
        # >20 min learner window flagged on Florian's return.
        r = timer.user_message("s1", now=at(47))
        self.assertGreater(r["returned_after_s"], timer.LONG_PERIOD_S)
        timer.coach_stream_end("s1", "réponse", now=at(48))
        timer.stop("s1", now=at(50))
        s = timer.summary("s1", now=at(50))
        self.assertTrue(s["stopped"])
        self.assertTrue(s["needs_confirmation"])  # the 21-min learner window stays flagged
        self.assertEqual(round(s["session_minutes"]), 30)  # coach 6 + learner 24, pauses exclues

    def test_single_active_and_resume_same_id(self):
        timer.start("s1", now=at(0))
        with self.assertRaises(ValueError):
            timer.start("s2", now=at(1))  # another active session is refused
        s = timer.start("s1", now=at(2))  # same id resumes
        self.assertFalse(s["stopped"])

    def test_stream_end_during_pause_resumes_on_learner(self):
        timer.start("s1", now=at(0))
        timer.pause("s1", now=at(1))
        timer.coach_stream_end("s1", "question", now=at(2))  # stream finished while paused
        s = timer.get("s1")
        self.assertEqual(s["resume_period"]["kind"], "learner")
        timer.resume("s1", now=at(3))
        self.assertEqual(kinds(timer.get("s1"))[-1], ("learner", "question"))

    def test_save_attaches_timing_and_confirmation(self):
        state = {"version": 1, "language": "ko", "calibration": [], "profile": {"objective": "Test", "level": "A1"}, "start": "2026-09-20", "target": "2026-12-07", "next": "x",
                 "resume": None, "sessions": [], "cards": [], "reviews": [],
                 "recordings": [], "checkpoints": [], "review_engine": "anki"}
        with db.write() as conn:
            notebook.insert_version(conn, state)
        timer.start("2026-09-24-seance-1", now=at(0))
        timer.coach_stream_end("2026-09-24-seance-1", "tâche", now=at(1))
        timer.user_message("2026-09-24-seance-1", now=at(25))  # 24-min window
        timer.stop("2026-09-24-seance-1", now=at(30))
        patch = {"session": {"id": "s-x", "date": "2026-09-24", "minutes": 30,
                             "kind": "apprentissage", "summary": "ok", "evidence": "chrono",
                             "completed": True, "completion_evidence": "critères vus",
                             "timer_id": "2026-09-24-seance-1"}}
        with self.assertRaises(ValueError):  # >20 min window: time_confirmation required
            notebook.apply_update(patch)
        patch["session"]["time_confirmation"] = "Florian confirme : il travaillait."
        state = notebook.apply_update(patch)
        saved = state["sessions"][-1]
        self.assertEqual(saved["timer_id"], "2026-09-24-seance-1")
        self.assertTrue(saved["timing"]["stopped"])
        self.assertTrue(saved["timing"]["needs_confirmation"])
        self.assertEqual(saved["minutes"], 30)


if __name__ == "__main__":
    unittest.main()
