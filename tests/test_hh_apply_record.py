"""Tests for the /submit state recorder."""

import tempfile
import unittest
from pathlib import Path

from tools import hh_apply_record as hr
from tools import state_db


class RecorderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.path = state_db.init_db(self.repo)

    def tearDown(self):
        self.tmp.cleanup()

    def add_app(self, url="https://hh.ru/vacancy/123", role="ML Engineer", status="drafted"):
        conn = state_db.connect(self.path)
        try:
            app_id = state_db._insert_application(
                conn,
                {
                    "status": status,
                    "company": "Acme",
                    "role": role,
                    "source_url": url,
                    "cover_letter_used": "unknown",
                },
            )
            conn.commit()
        finally:
            conn.close()
        return app_id

    def read_app(self, app_id):
        conn = state_db.connect(self.path, readonly=True)
        try:
            return state_db.application_show(conn, application_id=app_id)
        finally:
            conn.close()

    def sources(self, app_id):
        conn = state_db.connect(self.path, readonly=True)
        try:
            return state_db.list_application_sources(conn, app_id)
        finally:
            conn.close()

    def negotiations(self, app_id):
        return [
            item for item in self.sources(app_id)
            if item["external_type"] == "negotiation"
        ]

    def events(self, app_id, event_type=None):
        conn = state_db.connect(self.path, readonly=True)
        try:
            sql = "SELECT * FROM application_events WHERE application_id=?"
            params = [app_id]
            if event_type:
                sql += " AND event_type=?"
                params.append(event_type)
            return [dict(row) for row in conn.execute(sql, params)]
        finally:
            conn.close()

    def test_drafted_moves_to_applied_and_stores_negotiation(self):
        app_id = self.add_app()
        result = hr.record_submission(
            self.repo,
            url="https://hh.ru/vacancy/123",
            response_id="9001",
            cover_letter_used="not_used",
            applied_on="2026-11-11",
        )
        app = self.read_app(app_id)["application"]
        sources = self.negotiations(app_id)
        submitted = self.events(app_id, "submitted")

        self.assertEqual(result["application_id"], app_id)
        self.assertEqual(result["response_stored"], "9001")
        self.assertEqual(app["status"], "applied")
        self.assertEqual(app["applied_on"], "2026-11-11")
        self.assertEqual(app["cover_letter_used"], "not_used")
        self.assertEqual(len(sources), 1)
        self.assertEqual(
            (sources[0]["source"], sources[0]["external_type"], sources[0]["external_id"]),
            ("hh", "negotiation", "9001"),
        )
        self.assertEqual(len(submitted), 1)

    def test_duplicate_negotiation_fails_before_status_change(self):
        first = self.add_app(url="https://hh.ru/vacancy/123", role="ML Engineer")
        second = self.add_app(url="https://hh.ru/vacancy/456", role="Data Scientist")
        hr.record_submission(
            self.repo,
            url="https://hh.ru/vacancy/123",
            response_id="9001",
            cover_letter_used="not_used",
            applied_on="2026-11-11",
        )
        with self.assertRaises(state_db.StateError):
            hr.record_submission(
                self.repo,
                url="https://hh.ru/vacancy/456",
                response_id="9001",
                cover_letter_used="not_used",
                applied_on="2026-11-11",
            )
        # The duplicate raised before application_update, so the second row is
        # still a draft and its source list is untouched.
        second_app = self.read_app(second)["application"]
        self.assertEqual(second_app["status"], "drafted")
        self.assertIsNone(second_app["applied_on"])
        self.assertEqual(self.negotiations(second), [])

    def test_unknown_url_does_not_create_an_application(self):
        with self.assertRaises(state_db.StateError):
            hr.record_submission(
                self.repo,
                url="https://hh.ru/vacancy/999",
                response_id="1",
                cover_letter_used="not_used",
            )
        conn = state_db.connect(self.path, readonly=True)
        try:
            count = conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
        finally:
            conn.close()
        self.assertEqual(count, 0)

    def test_jobs_table_is_untouched(self):
        conn = state_db.connect(self.path)
        try:
            state_db.upsert_job(
                conn,
                {
                    "title": "ML Engineer",
                    "company": "Acme",
                    "url": "https://hh.ru/vacancy/123",
                    "status": "ranked",
                },
                key="acme_ml",
            )
            conn.commit()
            before = dict(conn.execute("SELECT * FROM jobs WHERE job_key='acme_ml'").fetchone())
        finally:
            conn.close()

        self.add_app()
        hr.record_submission(
            self.repo,
            url="https://hh.ru/vacancy/123",
            response_id="9001",
            cover_letter_used="not_used",
            applied_on="2026-11-11",
        )

        conn = state_db.connect(self.path, readonly=True)
        try:
            after = dict(conn.execute("SELECT * FROM jobs WHERE job_key='acme_ml'").fetchone())
        finally:
            conn.close()
        self.assertEqual(before, after)

    def test_response_id_is_optional(self):
        app_id = self.add_app()
        result = hr.record_submission(
            self.repo,
            url="https://hh.ru/vacancy/123",
            response_id=None,
            cover_letter_used="not_required",
            applied_on="2026-11-11",
        )
        self.assertEqual(result["response_stored"], "")
        self.assertEqual(self.negotiations(app_id), [])
        self.assertEqual(self.read_app(app_id)["application"]["status"], "applied")


if __name__ == "__main__":
    unittest.main()
