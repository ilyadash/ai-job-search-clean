"""Phase 0 database migration, source refs, events, and views."""

import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from tools import state_db


class MigrationTests(unittest.TestCase):
    def test_migrate_upgrades_v1_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "state" / "migrations").mkdir(parents=True)
            shutil.copy2(
                Path("state/migrations/001_init.sql"),
                repo / "state/migrations/001_init.sql",
            )
            for name in ("002_phase0.sql", "003_timeline_events.sql", "004_technical_round_2.sql"):
                shutil.copy2(
                    Path("state/migrations") / name,
                    repo / "state/migrations" / name,
                )
            db = repo / "state/job_search.sqlite"
            conn = sqlite3.connect(db)
            try:
                conn.executescript((repo / "state/migrations/001_init.sql").read_text(encoding="utf-8"))
                conn.execute(
                    "INSERT INTO jobs (job_key,title,company,url,status,created_at,updated_at) "
                    "VALUES (?,?,?,?,?,?,?)",
                    ("a", "ML", "Acme", "https://hh.ru/vacancy/123", "new", "2026-10-01", "2026-10-01"),
                )
                conn.execute(
                    "INSERT INTO applications (created_at,updated_at,applied_on,status,company,company_norm,role,role_norm,source_url,date_resolved,origin) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    ("2026-10-01", "2026-10-01", "2026-10-02", "rejected", "Acme", "acme", "ML", "ml", "https://hh.ru/vacancy/123", "2026-10-05", "legacy"),
                )
                conn.commit()
            finally:
                conn.close()
            result = state_db.migrate(repo)
            self.assertEqual(result["from"], 1)
            self.assertEqual(result["to"], 4)
            self.assertIn("002_phase0.sql", result["applied"])
            self.assertIn("003_timeline_events.sql", result["applied"])
            self.assertIn("004_technical_round_2.sql", result["applied"])
            self.assertIsNotNone(result["backup"])
            again = state_db.migrate(repo)
            self.assertEqual(again["applied"], [])
            conn = state_db.connect(db, readonly=True)
            try:
                self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 4)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0], 1)
                self.assertEqual(conn.execute("SELECT COUNT(*) FROM application_sources").fetchone()[0], 1)
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM application_events WHERE event_type='submitted'").fetchone()[0],
                    1,
                )
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM application_events WHERE event_type='rejected'").fetchone()[0],
                    1,
                )
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0],
                    4,
                )
            finally:
                conn.close()


class Phase0DataTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.path = state_db.init_db(self.repo)
        self.conn = state_db.connect(self.path)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def add_app(self, url="https://hh.ru/vacancy/123?tech_source=api", **over):
        values = {
            "applied_on": "2026-10-21",
            "status": "applied",
            "company": "Acme",
            "role": "ML Engineer",
            "source_url": url,
            "cover_letter_used": "unknown",
            "origin": "test",
        }
        values.update(over)
        app_id = state_db._insert_application(self.conn, values)
        self.conn.commit()
        return app_id

    def test_vacancy_source_is_created_and_can_hold_multiple_applications(self):
        first = self.add_app()
        second = self.add_app(role="Senior ML Engineer")
        sources = state_db.list_application_sources(self.conn, first)
        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["source"], "hh")
        self.assertEqual(sources[0]["external_type"], "vacancy")
        self.assertEqual(sources[0]["external_id"], "123")
        self.assertEqual(len(state_db.list_application_sources(self.conn, second)), 1)
        state_db.upsert_application_source(
            self.conn,
            first,
            source="hh",
            external_type="negotiation",
            external_id="9001",
            last_state="response",
        )
        self.conn.commit()
        with self.assertRaises(state_db.StateError):
            state_db.upsert_application_source(
                self.conn,
                second,
                source="hh",
                external_type="negotiation",
                external_id="9001",
                last_state="response",
            )

    def test_sync_state_roundtrip(self):
        state_db.set_sync_state(self.conn, "hh", cursor="page-2", metadata={"account": "x"})
        self.conn.commit()
        row = state_db.get_sync_state(self.conn, "hh")
        self.assertEqual(row["cursor"], "page-2")
        self.assertEqual(json.loads(row["metadata_json"])["account"], "x")

    def test_backfill_events_is_idempotent(self):
        app_id = self.add_app(
            applied_on="2026-10-21",
            first_response_date="2026-10-22",
            status="rejected",
            date_resolved="2026-10-25",
        )
        state_db._set_stage(self.conn, app_id, "technical", True, "2026-10-23", "test")
        self.conn.commit()
        first = state_db.backfill_phase0(self.conn, self.repo)
        second = state_db.backfill_phase0(self.conn, self.repo)
        events = [
            dict(row)
            for row in self.conn.execute(
                "SELECT event_type, event_date, source, recorded_at FROM application_events WHERE application_id=? ORDER BY event_type",
                (app_id,),
            )
        ]
        self.assertGreaterEqual(first["events"], 3)
        self.assertEqual(second["events"], 0)
        self.assertEqual(
            {row["event_type"] for row in events},
            {"submitted", "response_received", "rejected", "stage_reached"},
        )
        self.assertTrue(all(row["recorded_at"] for row in events))

    def test_record_outcome_writes_events_and_dates(self):
        result = state_db.record_outcome(
            self.conn,
            company="Acme",
            role="ML Engineer",
            status="applied",
            applied_on="2026-10-21",
            note="sent via portal",
        )
        app_id = result["id"]
        events = [
            dict(row)
            for row in self.conn.execute(
                "SELECT event_type, event_date, text FROM application_events WHERE application_id=? ORDER BY id",
                (app_id,),
            )
        ]
        self.assertEqual({row["event_type"] for row in events}, {"submitted", "note"})
        self.assertEqual(events[0]["event_date"], "2026-10-21")

    def test_jobs_description_fields_and_views(self):
        job = state_db.upsert_job(
            self.conn,
            {
                "title": "ML",
                "company": "Acme",
                "url": "https://hh.ru/vacancy/123",
                "description_text": "Build models",
                "language": "en",
            },
            key="acme_ml",
        )
        self.conn.commit()
        self.assertEqual(job["description_text"], "Build models")
        self.assertEqual(len(job["description_hash"]), 64)
        self.assertEqual(job["language"], "en")
        updated = state_db.upsert_job(
            self.conn,
            {
                "title": "ML",
                "company": "Acme",
                "url": "https://hh.ru/vacancy/123",
                "description_text": "Build better models",
            },
            key="acme_ml",
        )
        self.assertNotEqual(updated["description_hash"], job["description_hash"])
        self.assertEqual(updated["description_text"], "Build better models")
        views = {
            row[0]
            for row in self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='view'"
            )
        }
        self.assertIn("v_application_current", views)
        self.assertIn("v_application_timeline", views)
        self.assertIn("v_open_pipeline", views)

    def test_application_current_view_exposes_latest_state(self):
        app_id = self.add_app()
        state_db.backfill_phase0(self.conn, self.repo)
        row = dict(self.conn.execute("SELECT * FROM v_application_current WHERE id=?", (app_id,)).fetchone())
        self.assertEqual(row["status"], "applied")
        self.assertEqual(row["last_event_type"], "submitted")
        self.assertEqual(row["source_count"], 1)
        self.assertEqual(row["hh_state"], "")


if __name__ == "__main__":
    unittest.main()
