"""Tests for the archived-postings job-description backfill."""

import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tools import state_db


class JobDescriptionBackfillTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.path = state_db.init_db(self.repo)
        self.conn = state_db.connect(self.path)
        self.archive = "documents/applications/acme_ml_engineer"
        self.posting = self.repo / self.archive / "job_posting.md"
        self.posting.parent.mkdir(parents=True)
        self.posting.write_text("We build machine learning systems.", encoding="utf-8")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def add_job(self, key="acme_ml", url="https://hh.ru/vacancy/123", title="ML Engineer", company="Acme"):
        state_db.upsert_job(
            self.conn,
            {"title": title, "company": company, "url": url, "status": "ranked"},
            key=key,
        )
        self.conn.commit()

    def add_app(self, *, job_key="", source="", company="Acme", role="ML Engineer", archive=None):
        values = {
            "status": "applied",
            "company": company,
            "role": role,
            "source_url": source,
            "archive_path": archive if archive is not None else self.archive,
            "origin": "test",
        }
        if job_key:
            values["job_key"] = job_key
        app_id = state_db._insert_application(self.conn, values)
        self.conn.commit()
        return app_id

    def test_matches_by_job_key_and_writes_description(self):
        self.add_job()
        app_id = self.add_app(job_key="acme_ml")
        before = state_db._job_row(self.conn, "acme_ml")
        dry = state_db.backfill_job_descriptions(self.conn, self.repo)
        after_dry = state_db._job_row(self.conn, "acme_ml")
        self.assertEqual(dry["would_update"], 1)
        self.assertEqual(after_dry["description_text"], "")
        result = state_db.backfill_job_descriptions(self.conn, self.repo, write=True)
        job = state_db._job_row(self.conn, "acme_ml")
        app = state_db._application_row(self.conn, app_id)
        self.assertEqual(result["updated"], 1)
        self.assertEqual(job["description_text"], "We build machine learning systems.")
        self.assertEqual(job["language"], "en")
        self.assertEqual(len(job["description_hash"]), 64)
        self.assertEqual(job["updated_at"], before["updated_at"])
        self.assertEqual(app["status"], "applied")

    def test_matches_by_normalized_url(self):
        self.add_job(url="https://hh.ru/vacancy/123?utm_source=x")
        self.add_app(source="https://hh.ru/vacancy/123/?from=search")
        result = state_db.backfill_job_descriptions(self.conn, self.repo, write=True)
        self.assertEqual(result["updated"], 1)
        self.assertEqual(result["details"][0]["match"], "url")

    def test_falls_back_to_unique_company_and_title(self):
        self.add_job(url="https://example.com/other")
        self.add_app(company="Acme", role="ML Engineer")
        result = state_db.backfill_job_descriptions(self.conn, self.repo, write=True)
        self.assertEqual(result["updated"], 1)
        self.assertEqual(result["details"][0]["match"], "company_title")

    def test_ambiguous_fallback_writes_nothing(self):
        self.add_job(key="acme_one", url="https://example.com/one")
        self.add_job(key="acme_two", url="https://example.com/two")
        self.add_app()
        result = state_db.backfill_job_descriptions(self.conn, self.repo, write=True)
        self.assertEqual(result["ambiguous"], 1)
        self.assertEqual(result["updated"], 0)
        self.assertEqual(len(result["details"][0]["candidates"]), 2)
        self.assertEqual(state_db._job_row(self.conn, "acme_one")["description_text"], "")

    def test_unmatched_does_not_create_a_job(self):
        self.add_app()
        result = state_db.backfill_job_descriptions(self.conn, self.repo, write=True)
        self.assertEqual(result["unmatched"], 1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 0)

    def test_uses_file_mtime_for_archive_import(self):
        self.add_job()
        self.add_app(job_key="acme_ml")
        os.utime(self.posting, (1700000000, 1700000000))
        state_db.backfill_job_descriptions(self.conn, self.repo, write=True)
        job = state_db._job_row(self.conn, "acme_ml")
        expected = datetime.fromtimestamp(1700000000, tz=timezone.utc).isoformat(timespec="seconds")
        self.assertEqual(job["description_fetched_at"], expected)

    def test_existing_description_requires_replace(self):
        self.add_job()
        self.add_app(job_key="acme_ml")
        self.conn.execute(
            "UPDATE jobs SET description_text='old text', description_hash='old' WHERE job_key='acme_ml'"
        )
        self.conn.commit()
        skipped = state_db.backfill_job_descriptions(self.conn, self.repo, write=True)
        self.assertEqual(skipped["skipped_existing"], 1)
        self.assertEqual(state_db._job_row(self.conn, "acme_ml")["description_text"], "old text")
        replaced = state_db.backfill_job_descriptions(
            self.conn, self.repo, write=True, replace=True
        )
        self.assertEqual(replaced["updated"], 1)
        self.assertEqual(
            state_db._job_row(self.conn, "acme_ml")["description_text"],
            "We build machine learning systems.",
        )

    def test_second_run_is_idempotent(self):
        self.add_job()
        self.add_app(job_key="acme_ml")
        state_db.backfill_job_descriptions(self.conn, self.repo, write=True)
        second = state_db.backfill_job_descriptions(self.conn, self.repo, write=True)
        self.assertEqual(second["updated"], 0)
        self.assertEqual(second["unchanged"], 1)

    def test_missing_posting_is_reported(self):
        self.add_job()
        self.add_app(job_key="acme_ml", archive="documents/applications/missing")
        result = state_db.backfill_job_descriptions(self.conn, self.repo)
        self.assertEqual(result["missing_posting"], 1)
        self.assertEqual(result["updated"], 0)

    def test_wrong_posting_identity_is_not_ingested(self):
        self.add_job(url="https://hh.ru/vacancy/123")
        self.add_app(source="https://hh.ru/vacancy/123")
        self.posting.write_text(
            "# ML Engineer\n\nSource: https://hh.ru/vacancy/999\n", encoding="utf-8"
        )
        result = state_db.backfill_job_descriptions(self.conn, self.repo, write=True)
        self.assertEqual(result["identity_mismatch"], 1)
        self.assertEqual(result["updated"], 0)
        self.assertEqual(state_db._job_row(self.conn, "acme_ml")["description_text"], "")

    def test_detect_language(self):
        self.assertEqual(state_db.detect_language("Мы строим ML-системы"), "ru")
        self.assertEqual(state_db.detect_language("We build ML systems"), "en")
        self.assertEqual(state_db.detect_language(""), "unknown")


if __name__ == "__main__":
    unittest.main()
