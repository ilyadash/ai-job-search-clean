"""Text-to-database migration and single-write pipeline guards."""

import sqlite3
import tempfile
import unittest
from pathlib import Path

from tools import state_db

try:
    from tests._candidate import SAMPLE_NAME
except ImportError:  # `python -m unittest discover -s tests` imports test modules top-level
    from _candidate import SAMPLE_NAME


class TextMigrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.path = state_db.init_db(self.repo)
        self.conn = state_db.connect(self.path)
        self.conn.row_factory = sqlite3.Row

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def add_app(self, *, company="Acme", role="ML Engineer", status="applied", archive="acme_ml", **over):
        values = {
            "status": status,
            "company": company,
            "role": role,
            "archive_path": f"documents/applications/{archive}" if archive else "",
            "origin": "test",
        }
        values.update(over)
        app_id = state_db._insert_application(self.conn, values)
        self.conn.commit()
        return app_id

    def write_outcome(self, archive: str, text: str) -> Path:
        folder = self.repo / "documents" / "applications" / archive
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "outcome.md"
        path.write_text(text, encoding="utf-8")
        return path

    def write_posting(self, archive: str, text: str, name: str = "job_posting.md") -> Path:
        folder = self.repo / "documents" / "applications" / archive
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / name
        path.write_text(text, encoding="utf-8")
        return path

    def events(self, app_id):
        return [
            dict(row)
            for row in self.conn.execute(
                "SELECT event_date, event_type, text, source FROM application_events "
                "WHERE application_id=? ORDER BY event_date, id",
                (app_id,),
            )
        ]

    def test_migrates_status_date_stages_and_dated_notes_then_strips(self):
        app_id = self.add_app()
        outcome = self.write_outcome(
            "acme_ml",
            "# Outcome: Acme — ML Engineer\n\n"
            "**Status:** rejected\n\n"
            "**Date resolved:** 2026-10-02\n\n"
            "## Interview stages reached\n"
            "- [x] Phone screen (2026-10-01)\n"
            "- [ ] Technical interview\n\n"
            "## Notes\n"
            "- 2026-09-22: sent via hh\n"
            "- 2026-10-02: rejected\n"
            "- Undated feedback survives\n",
        )
        dry = state_db.migrate_text_state(self.conn, self.repo)
        self.assertEqual(dry["notes_created"], 2)
        self.assertEqual(outcome.read_text(encoding="utf-8").count("**Status:**"), 1)

        result = state_db.migrate_text_state(
            self.conn, self.repo, write=True, strip_outcome=True
        )
        row = state_db._application_row(self.conn, app_id)
        self.assertEqual(row["status"], "applied")
        self.assertEqual(row["date_resolved"], "2026-10-02")
        stage = self.conn.execute(
            "SELECT * FROM application_stages WHERE application_id=? AND stage='phone_screen'",
            (app_id,),
        ).fetchone()
        self.assertIsNotNone(stage)
        notes = [event for event in self.events(app_id) if event["event_type"] == "note"]
        self.assertEqual([event["event_date"] for event in notes], ["2026-09-22", "2026-10-02"])
        stripped = outcome.read_text(encoding="utf-8")
        self.assertNotIn("**Status:**", stripped)
        self.assertNotIn("Interview stages reached", stripped)
        self.assertNotIn("2026-09-22: sent via hh", stripped)
        self.assertIn("Undated feedback survives", stripped)
        self.assertGreaterEqual(result["stripped"], 1)

        again = state_db.migrate_text_state(self.conn, self.repo, write=True, strip_outcome=True)
        self.assertEqual(again["notes_created"], 0)

    def test_migrates_dated_application_notes_and_keeps_context(self):
        app_id = self.add_app(status="applied", notes="keep context; 2026-10-01: sent; 2026-10-02: rejected")
        result = state_db.migrate_text_state(self.conn, self.repo, write=True)
        self.assertEqual(result["notes_removed"], 2)
        row = state_db._application_row(self.conn, app_id)
        self.assertEqual(row["notes"], "keep context")
        notes = [event for event in self.events(app_id) if event["event_type"] == "note"]
        self.assertEqual(len(notes), 2)
        self.assertEqual({event["source"] for event in notes}, {"legacy-notes"})
        again = state_db.migrate_text_state(self.conn, self.repo, write=True)
        self.assertEqual(again["notes_created"], 0)

    def test_shared_outcome_is_mapped_by_dates_not_duplicated(self):
        first = self.add_app(
            company="DaData", role="AI/LLM инженер", archive="dadata",
            applied_on="2026-08-25", date_resolved="2026-08-28", status="rejected",
        )
        second = self.add_app(
            company="DaData", role="AI/LLM инженер", archive="dadata",
            applied_on="2026-10-20", status="applied",
        )
        self.write_outcome(
            "dadata",
            "# Outcome: DaData — AI/LLM инженер\n"
            "## Notes\n- 2026-08-25: sent\n- 2026-08-28: rejected\n",
        )
        result = state_db.migrate_text_state(self.conn, self.repo, write=True)
        self.assertEqual(result["ambiguous"], [])
        first_notes = [e for e in self.events(first) if e["event_type"] == "note"]
        second_notes = [e for e in self.events(second) if e["event_type"] == "note"]
        self.assertEqual(len(first_notes), 2)
        self.assertEqual(second_notes, [])

    def test_archived_jobs_are_created_linked_and_deduplicated(self):
        first = self.add_app(
            company="Acme", role="ML Engineer", archive="acme_one",
            source_url="https://hh.ru/vacancy/1000001",
        )
        second = self.add_app(
            company="Acme", role="ML Engineer", archive="acme_two",
            source_url="https://hh.ru/vacancy/1000002",
        )
        third = self.add_app(
            company="Acme", role="ML Engineer", archive="acme_three",
            source_url="https://hh.ru/vacancy/1000001",
        )
        for archive, vacancy in (
            ("acme_one", 1000001), ("acme_two", 1000002), ("acme_three", 1000001)
        ):
            self.write_posting(archive, f"# ML Engineer\n\nSource: https://hh.ru/vacancy/{vacancy}\n\nText {vacancy}")

        dry = state_db.backfill_archived_jobs(self.conn, self.repo)
        self.assertEqual(dry["created"], 2)
        result = state_db.backfill_archived_jobs(self.conn, self.repo, write=True)
        self.assertEqual(result["created"], 2)
        jobs = [dict(row) for row in self.conn.execute("SELECT * FROM jobs ORDER BY job_key")]
        self.assertEqual(len(jobs), 2)
        self.assertTrue(all(job["status"] == "archived" for job in jobs))
        self.assertEqual(len({job["job_key"] for job in jobs}), 2)
        rows = [state_db._application_row(self.conn, app_id) for app_id in (first, second, third)]
        self.assertEqual(rows[0]["job_key"], rows[2]["job_key"])
        self.assertNotEqual(rows[0]["job_key"], rows[1]["job_key"])
        self.assertTrue(all(row["description_text"] for row in jobs))
        again = state_db.backfill_archived_jobs(self.conn, self.repo, write=True)
        self.assertEqual(again["created"], 0)

    def test_existing_job_is_reused_and_mismatched_job_key_is_relinked(self):
        self.conn.execute(
            "INSERT INTO jobs (job_key,title,company,company_norm,url,url_norm,status,created_at,updated_at) "
            "VALUES ('old_key','ML Engineer','Acme','acme','https://hh.ru/vacancy/1','https://hh.ru/vacancy/1','new','2026-01-01','2026-01-01')"
        )
        self.conn.commit()
        app_id = self.add_app(
            company="Acme", role="ML Engineer", archive="acme_new",
            source_url="https://hh.ru/vacancy/2", job_key="old_key",
        )
        self.write_posting("acme_new", "# ML Engineer\n\nSource: https://hh.ru/vacancy/2\n\nNew text")
        result = state_db.backfill_archived_jobs(self.conn, self.repo, write=True)
        self.assertEqual(result["created"], 1)
        row = state_db._application_row(self.conn, app_id)
        self.assertNotEqual(row["job_key"], "old_key")
        job = state_db._job_row(self.conn, row["job_key"])
        self.assertEqual(job["url"], "https://hh.ru/vacancy/2")
        self.assertEqual(job["status"], "archived")

    def test_archived_jobs_are_excluded_from_rank_all(self):
        self.conn.execute(
            "INSERT INTO jobs (job_key,title,company,company_norm,url,url_norm,status,created_at,updated_at) "
            "VALUES ('archived','ML','Acme','acme','https://example.com/1','https://example.com/1','archived','2026-01-01','2026-01-01')"
        )
        self.conn.execute(
            "INSERT INTO jobs (job_key,title,company,company_norm,url,url_norm,status,created_at,updated_at) "
            "VALUES ('ranked','DS','Acme','acme','https://example.com/2','https://example.com/2','ranked','2026-01-01','2026-01-01')"
        )
        self.conn.commit()
        candidates = state_db.job_candidates(self.conn, show_all=True)
        self.assertEqual([item["key"] for item in candidates["selected"]], ["ranked"])

    def test_backfill_cover_letter_words_is_plain_text_only(self):
        app_id = self.add_app(status="applied", cover_letter_path="cover_letters/acme/cover.txt")
        letter = self.repo / "cover_letters" / "acme" / "cover.txt"
        letter.parent.mkdir(parents=True)
        letter.write_text(f"Здравствуйте!\n\nОдно два три.\n\nС уважением,\n{SAMPLE_NAME}\n", encoding="utf-8")
        result = state_db.backfill_cover_letter_words(self.conn, self.repo, write=True)
        self.assertEqual(result["updated"], 1)
        row = state_db._application_row(self.conn, app_id)
        self.assertEqual(row["cover_letter_words"], 3)


class PipelineSingleWriteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.path = state_db.init_db(self.repo)
        self.conn = state_db.connect(self.path)
        self.conn.row_factory = sqlite3.Row

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def add_app(self, **over):
        values = {
            "status": "applied",
            "company": "Acme",
            "role": "ML Engineer",
            "source_url": "https://hh.ru/vacancy/1",
            "notes": "context",
        }
        values.update(over)
        app_id = state_db._insert_application(self.conn, values)
        self.conn.commit()
        return app_id

    def test_update_note_is_written_only_to_events(self):
        app_id = self.add_app()
        state_db.application_update(self.conn, url="https://hh.ru/vacancy/1", note="call done")
        row = state_db._application_row(self.conn, app_id)
        self.assertEqual(row["notes"], "context")
        notes = self.conn.execute(
            "SELECT text FROM application_events WHERE application_id=? AND event_type='note'",
            (app_id,),
        ).fetchall()
        self.assertEqual([item["text"] for item in notes], ["call done"])

    def test_status_transition_writes_one_status_event(self):
        app_id = self.add_app(date_resolved=None)
        state_db.application_update(
            self.conn,
            url="https://hh.ru/vacancy/1",
            status="rejected",
            date_resolved="2026-10-02",
        )
        events = self.conn.execute(
            "SELECT event_type, text FROM application_events WHERE application_id=? AND event_type='rejected'",
            (app_id,),
        ).fetchall()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["text"], "Status changed to rejected")

    def test_record_outcome_does_not_infer_dates(self):
        app_id = self.add_app(applied_on=None, date_resolved=None, status="applied")
        state_db.record_outcome(
            self.conn,
            company="Acme",
            role="ML Engineer",
            status="rejected",
        )
        row = state_db._application_row(self.conn, app_id)
        self.assertIsNone(row["applied_on"])
        self.assertIsNone(row["date_resolved"])

    def test_record_outcome_note_is_not_duplicated_in_notes(self):
        app_id = self.add_app()
        state_db.record_outcome(
            self.conn,
            company="Acme",
            role="ML Engineer",
            status="applied",
            note="sent",
        )
        row = state_db._application_row(self.conn, app_id)
        self.assertEqual(row["notes"], "context")
        count = self.conn.execute(
            "SELECT COUNT(*) FROM application_events WHERE application_id=? AND event_type='note'",
            (app_id,),
        ).fetchone()[0]
        self.assertEqual(count, 1)


if __name__ == "__main__":
    unittest.main()
