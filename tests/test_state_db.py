"""Tests for the SQLite state database and its import/recording APIs."""

import csv
import json
import tempfile
import unittest
from pathlib import Path

from tools import state_db


def write_tracker(repo: Path, rows: list[dict[str, str]]) -> None:
    header = [
        "date", "company", "sector", "role", "role_type", "channel", "status",
        "contact_person", "fit_rating", "notes", "cv_file", "cover_letter_file",
        "source", "deadline",
    ]
    path = repo / "job_search_tracker.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in header})


def write_seen(repo: Path, entries: dict) -> None:
    path = repo / "job_scraper" / "seen_jobs.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"seen": entries}, ensure_ascii=False), encoding="utf-8")


class StateDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.path = state_db.init_db(self.repo)

    def tearDown(self):
        self.tmp.cleanup()

    def test_init_creates_views_and_query_rejects_writes(self):
        result = state_db.query(
            "SELECT name FROM sqlite_master WHERE type = 'view' ORDER BY name",
            repo=self.repo,
        )
        names = {row["name"] for row in result["rows"]}
        self.assertIn("v_funnel", names)
        self.assertIn("v_cover_letter", names)
        with self.assertRaises(state_db.StateError):
            state_db.query("DELETE FROM applications", repo=self.repo)

    def test_job_upsert_and_context(self):
        conn = state_db.connect(self.path)
        try:
            state_db.upsert_job(
                conn,
                {
                    "title": "ML Engineer",
                    "company": "Acme",
                    "url": "https://example.com/jobs/1",
                    "first_seen": "2026-10-20",
                    "status": "new",
                    "portal": "hhru-search",
                    "source": "cli",
                },
                key="acme_ml-engineer",
            )
            conn.commit()
            context = state_db.job_context(conn)
            candidates = state_db.job_candidates(conn)
        finally:
            conn.close()
        self.assertEqual(candidates["selected"][0]["key"], "acme_ml-engineer")
        self.assertEqual(context["company_titles"][0][0], "acme")

    def test_record_draft_then_outcome_and_cover_letter(self):
        letter = self.repo / "cover_letters" / "acme" / "cover.txt"
        letter.parent.mkdir(parents=True)
        letter.write_text("Здравствуйте!\n\nТекст.\n", encoding="utf-8")
        posting = self.repo / "posting.md"
        posting.write_text("# Vacancy\n\n" + "text " * 100, encoding="utf-8")
        conn = state_db.connect(self.path)
        try:
            draft = state_db.record_draft(
                conn,
                company="Acme",
                role="ML Engineer",
                fit=80,
                letter=str(letter),
                source="https://example.com/jobs/1",
                posting_file=str(posting),
                today="2026-10-21",
                repo=self.repo,
            )
            self.assertEqual(draft["row"]["status"], "drafted")
            self.assertEqual(draft["row"]["cover_letter_used"], "unknown")
            self.assertEqual(draft["archive"], "written")
            outcome = state_db.record_outcome(
                conn,
                company="Acme",
                role="ML Engineer",
                status="applied",
                applied_on="2026-10-22",
                cover_letter_used="used",
                stages=["Phone screen (2026-10-24)"],
                note="sent via portal",
            )
            self.assertEqual(outcome["row"]["status"], "applied")
            self.assertEqual(outcome["row"]["cover_letter_used"], "used")
            self.assertEqual(outcome["row"]["applied_on"], "2026-10-22")
            self.assertEqual(len(outcome["row"]["stages"]), 1)
            stats = state_db.compute_stats(conn)
        finally:
            conn.close()
        self.assertEqual(stats["applications"]["submitted"], 1)
        self.assertEqual(stats["cover_letter"]["used"]["n"], 1)
        self.assertEqual(stats["funnel"]["interview"]["successes"], 1)

    def test_record_outcome_keeps_applied_on_unknown(self):
        conn = state_db.connect(self.path)
        try:
            outcome = state_db.record_outcome(
                conn,
                company="Acme",
                role="ML Engineer",
                status="interview",
                applied_on="unknown",
                first_response_date="2026-10-29",
                stages=["Phone screen (2026-10-29)"],
                note="recruiter call; technical interview scheduled",
            )
        finally:
            conn.close()
        self.assertIsNone(outcome["row"]["applied_on"])
        self.assertEqual(outcome["row"]["first_response_date"], "2026-10-29")

    def test_backup_creates_readable_copy(self):
        target = self.repo / "backup.sqlite"
        result = state_db.backup(self.repo, target)
        self.assertTrue(result.is_file())
        conn = state_db.connect(result, readonly=True)
        try:
            self.assertIsNotNone(conn.execute("SELECT 1").fetchone())
        finally:
            conn.close()

    def test_import_legacy_imports_jobs_applications_and_unknowns(self):
        write_seen(
            self.repo,
            {
                "acme_ml": {
                    "title": "ML Engineer",
                    "company": "Acme",
                    "url": "https://example.com/jobs/1",
                    "first_seen": "2026-10-01",
                    "status": "new",
                    "portal": "hhru-search",
                    "source": "cli",
                }
            },
        )
        write_tracker(
            self.repo,
            [
                {
                    "date": "2026-10-02",
                    "company": "Acme",
                    "role": "ML Engineer",
                    "status": "applied",
                    "fit_rating": "77",
                    "source": "https://example.com/jobs/1",
                    "cover_letter_file": "cover_letters/acme/cover.txt",
                }
            ],
        )
        report = state_db.import_legacy(repo=self.repo)
        self.assertEqual(report["jobs"], 1)
        self.assertEqual(report["applications"], 1)
        self.assertEqual(report["cover_letter_unknown"], 1)
        conn = state_db.connect(self.path, readonly=True)
        try:
            row = conn.execute("SELECT * FROM applications").fetchone()
            self.assertEqual(row["status"], "applied")
            self.assertEqual(row["cover_letter_used"], "unknown")
            self.assertEqual(row["fit_rating"], 77)
            self.assertIsNone(row["cv_version_id"])
        finally:
            conn.close()

    def test_job_apply_rank_updates_fields(self):
        conn = state_db.connect(self.path)
        try:
            state_db.upsert_job(conn, {"title": "ML", "company": "Acme", "status": "new"}, key="a")
            conn.commit()
            result = state_db.job_apply_rank(
                conn,
                [
                    {
                        "key": "a",
                        "status": "scored",
                        "scores": {"technical": 80, "experience": 60, "behavioral": 70, "career": 75},
                        "strengths": ["s1"],
                        "gaps": ["g1"],
                    }
                ],
                today="2026-10-21",
            )
            row = state_db._job_row(conn, "a")
        finally:
            conn.close()
        self.assertEqual(result["ranked"][0]["score"], 72)
        self.assertEqual(row["rank_verdict"], "Good Fit")
        self.assertEqual(row["strengths_json"], '["s1"]')


class ApplicationUrlApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        self.path = state_db.init_db(self.repo)
        self.conn = state_db.connect(self.path)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def add_job(self, url="https://example.com/jobs/1", **over):
        entry = {
            "title": "ML Engineer",
            "company": "Acme",
            "url": url,
            "status": "ranked",
            "rank_score": 80,
        }
        entry.update(over)
        state_db.upsert_job(self.conn, entry, key="acme_ml")
        self.conn.commit()

    def add_app(self, url="https://example.com/jobs/1", company="Acme", role="ML Engineer", status="applied"):
        app_id = state_db._insert_application(
            self.conn,
            {
                "applied_on": "2026-10-21",
                "status": status,
                "company": company,
                "role": role,
                "source_url": url,
                "fit_rating": 77,
                "cover_letter_used": "unknown",
                "job_key": "acme_ml",
                "origin": "test",
            },
        )
        self.conn.commit()
        return app_id

    def test_show_by_normalized_url_and_job(self):
        self.add_job("https://example.com/jobs/1?utm_source=x")
        app_id = self.add_app("https://example.com/jobs/1?utm_source=x")
        result = state_db.application_show(self.conn, url="https://example.com/jobs/1/")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["application"]["id"], app_id)
        self.assertEqual(result["job"]["company"], "Acme")

    def test_show_job_only_and_not_found(self):
        self.add_job()
        job_only = state_db.application_show(self.conn, url="https://example.com/jobs/1")
        self.assertEqual(job_only["status"], "job_only")
        self.assertIsNone(job_only["application"])
        missing = state_db.application_show(self.conn, url="https://example.com/jobs/404")
        self.assertEqual(missing["status"], "not_found")

    def test_ambiguous_url_returns_candidates_and_refuses_update(self):
        self.add_job()
        first = self.add_app()
        second = self.add_app(role="Senior ML Engineer")
        result = state_db.application_show(self.conn, url="https://example.com/jobs/1")
        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual({row["id"] for row in result["matches"]}, {first, second})
        with self.assertRaises(state_db.StateError):
            state_db.application_update(
                self.conn,
                url="https://example.com/jobs/1",
                status="rejected",
            )

    def test_update_only_application_related_records(self):
        self.add_job()
        app_id = self.add_app()
        job_before = state_db._job_row(self.conn, "acme_ml")
        result = state_db.application_update(
            self.conn,
            url="https://example.com/jobs/1",
            status="rejected",
            cover_letter_used="used",
            first_response_date="2026-10-22",
            date_resolved="2026-10-23",
            stages=["Technical interview (2026-10-22)"],
            note="rejection email",
        )
        app = state_db._application_row(self.conn, app_id)
        job_after = state_db._job_row(self.conn, "acme_ml")
        stages = self.conn.execute(
            "SELECT * FROM application_stages WHERE application_id = ?", (app_id,)
        ).fetchall()
        events = self.conn.execute(
            "SELECT * FROM application_events WHERE application_id = ?", (app_id,)
        ).fetchall()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(app["status"], "rejected")
        self.assertEqual(app["cover_letter_used"], "used")
        self.assertEqual(app["first_response_date"], "2026-10-22")
        self.assertEqual(app["date_resolved"], "2026-10-23")
        self.assertEqual(len(stages), 1)
        self.assertEqual(stages[0]["stage"], "technical")
        event_types = {event["event_type"] for event in events}
        self.assertEqual(
            event_types,
            {"submitted", "response_received", "rejected", "stage_reached", "note"},
        )
        self.assertTrue(all(event["recorded_at"] for event in events))
        self.assertEqual(job_before["updated_at"], job_after["updated_at"])

    def test_technical_round_two_is_a_separate_stage(self):
        self.add_job()
        app_id = self.add_app()
        result = state_db.application_update(
            self.conn,
            url="https://example.com/jobs/1",
            stages=[
                "Technical interview (2026-11-03)",
                "Technical interview 2 (2026-11-06)",
            ],
        )
        app = state_db.application_show(self.conn, url="https://example.com/jobs/1")
        stages = {row["stage"]: row["date"] for row in app["application"]["stages"]}
        self.assertEqual(result["status"], "ok")
        self.assertEqual(stages["technical"], "2026-11-03")
        self.assertEqual(stages["technical_2"], "2026-11-06")
        events = self.conn.execute(
            "SELECT event_date, text FROM application_events "
            "WHERE application_id=? AND event_type='stage_reached' ORDER BY event_date",
            (app_id,),
        ).fetchall()
        self.assertEqual(
            [(row["event_date"], row["text"]) for row in events],
            [
                ("2026-11-03", "Stage reached: technical"),
                ("2026-11-06", "Stage reached: technical_2"),
            ],
        )

    def test_draft_resolves_company_and_role_from_job_url(self):
        self.add_job()
        letter = self.repo / "cover.txt"
        letter.write_text("Здравствуйте!\n\nТекст.\n", encoding="utf-8")
        result = state_db.record_draft(
            self.conn,
            company="",
            role="",
            fit=80,
            letter=str(letter),
            source="https://example.com/jobs/1",
            today="2026-10-21",
            repo=self.repo,
        )
        self.assertEqual(result["row"]["company"], "Acme")
        self.assertEqual(result["row"]["role"], "ML Engineer")

    def test_unknown_url_is_an_error_and_writes_nothing(self):
        before = self.conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
        with self.assertRaises(state_db.StateError):
            state_db.application_update(self.conn, url="https://example.com/missing", status="rejected")
        after = self.conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
        self.assertEqual(before, after)

    def test_application_id_disambiguates(self):
        self.add_job()
        first = self.add_app()
        self.add_app(role="Senior ML Engineer")
        result = state_db.application_update(
            self.conn,
            application_id=first,
            status="interview",
            stages=["Phone screen"],
        )
        self.assertEqual(result["application_id"], first)
        self.assertEqual(result["matched_by"], "id")

    def test_update_does_not_infer_applied_on_from_status(self):
        self.add_job()
        app_id = state_db._insert_application(
            self.conn,
            {
                "applied_on": None,
                "status": "interview",
                "company": "Acme",
                "role": "ML Engineer",
                "source_url": "https://example.com/jobs/1",
                "origin": "test",
            },
        )
        self.conn.commit()
        state_db.application_update(
            self.conn,
            url="https://example.com/jobs/1",
            status="interview",
            stages=["Technical interview (2026-11-09)"],
            today="2026-11-02",
        )
        app = state_db._application_row(self.conn, app_id)
        self.assertIsNone(app["applied_on"])

    def test_update_clears_applied_on_with_unknown(self):
        self.add_job()
        app_id = self.add_app()
        state_db.application_update(
            self.conn,
            url="https://example.com/jobs/1",
            applied_on="unknown",
            today="2026-11-02",
        )
        app = state_db._application_row(self.conn, app_id)
        self.assertIsNone(app["applied_on"])
        submitted = self.conn.execute(
            "SELECT COUNT(*) FROM application_events WHERE application_id=? AND event_type='submitted'",
            (app_id,),
        ).fetchone()[0]
        self.assertEqual(submitted, 0)

    def test_draft_to_submitted_still_sets_applied_on(self):
        self.add_job()
        app_id = state_db._insert_application(
            self.conn,
            {
                "applied_on": None,
                "status": "drafted",
                "company": "Acme",
                "role": "ML Engineer",
                "source_url": "https://example.com/jobs/1",
                "origin": "test",
            },
        )
        self.conn.commit()
        state_db.application_update(
            self.conn,
            url="https://example.com/jobs/1",
            status="applied",
            today="2026-11-02",
        )
        app = state_db._application_row(self.conn, app_id)
        self.assertEqual(app["applied_on"], "2026-11-02")

    def test_show_returns_latest_event(self):
        self.add_job()
        app_id = self.add_app()
        self.conn.execute(
            "INSERT INTO application_events "
            "(application_id, event_date, event_type, text, source, recorded_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (app_id, "2026-10-29", "note", "older note", "test", "2026-10-29T12:00:00+00:00"),
        )
        self.conn.execute(
            "INSERT INTO application_events "
            "(application_id, event_date, event_type, text, source, recorded_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (app_id, "2026-11-02", "note", "newer note", "test", "2026-11-02T12:00:00+00:00"),
        )
        self.conn.commit()
        result = state_db.application_show(self.conn, url="https://example.com/jobs/1")
        self.assertEqual(result["application"]["last_event"]["text"], "newer note")

    def test_delete_application_event_removes_auto_generated_row(self):
        self.add_job()
        app_id = self.add_app()
        cursor = self.conn.execute(
            "INSERT INTO application_events "
            "(application_id, event_date, event_type, text, source, recorded_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (app_id, "2026-11-02", "submitted", "Application submitted", "test", "2026-11-02T12:00:00+00:00"),
        )
        event_id = int(cursor.lastrowid)
        self.conn.commit()
        result = state_db.delete_application_event(
            self.conn,
            event_id=event_id,
            application_id=app_id,
        )
        self.assertEqual(result["status"], "ok")
        self.assertIsNone(
            self.conn.execute("SELECT 1 FROM application_events WHERE id=?", (event_id,)).fetchone()
        )

    def test_delete_note_event_removes_note_from_application_notes(self):
        self.add_job()
        app_id = self.add_app()
        self.conn.execute(
            "UPDATE applications SET notes=? WHERE id=?",
            ("2026-10-29: call done 2026-11-02: stray note", app_id),
        )
        cursor = self.conn.execute(
            "INSERT INTO application_events "
            "(application_id, event_date, event_type, text, source, recorded_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (app_id, "2026-11-02", "note", "stray note", "test", "2026-11-02T12:00:00+00:00"),
        )
        event_id = int(cursor.lastrowid)
        self.conn.commit()
        state_db.delete_application_event(self.conn, event_id=event_id, application_id=app_id)
        notes = self.conn.execute(
            "SELECT notes FROM applications WHERE id=?", (app_id,)
        ).fetchone()["notes"]
        self.assertEqual(notes, "2026-10-29: call done")

    def test_delete_application_event_rejects_wrong_application(self):
        self.add_job()
        app_id = self.add_app()
        cursor = self.conn.execute(
            "INSERT INTO application_events "
            "(application_id, event_date, event_type, text, source, recorded_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (app_id, "2026-11-02", "submitted", "Application submitted", "test", "2026-11-02T12:00:00+00:00"),
        )
        event_id = int(cursor.lastrowid)
        self.conn.commit()
        with self.assertRaises(state_db.StateError):
            state_db.delete_application_event(
                self.conn,
                event_id=event_id,
                application_id=app_id + 1,
            )

    def test_update_application_event_date_corrects_notes(self):
        self.add_job()
        app_id = self.add_app()
        self.conn.execute(
            "UPDATE applications SET notes=? WHERE id=?",
            ("2026-10-29: call done", app_id),
        )
        cursor = self.conn.execute(
            "INSERT INTO application_events "
            "(application_id, event_date, event_type, text, source, recorded_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (app_id, "2026-10-29", "note", "call done", "test", "2026-10-29T12:00:00+00:00"),
        )
        event_id = int(cursor.lastrowid)
        self.conn.commit()
        result = state_db.update_application_event(
            self.conn,
            event_id=event_id,
            event_date="2026-10-28",
            application_id=app_id,
        )
        event = self.conn.execute(
            "SELECT * FROM application_events WHERE id=?", (event_id,)
        ).fetchone()
        notes = self.conn.execute(
            "SELECT notes FROM applications WHERE id=?", (app_id,)
        ).fetchone()["notes"]
        self.assertEqual(result["event_date"], "2026-10-28")
        self.assertEqual(event["event_date"], "2026-10-28")
        self.assertEqual(notes, "2026-10-28: call done")

    def test_update_application_event_rejects_wrong_application(self):
        self.add_job()
        app_id = self.add_app()
        cursor = self.conn.execute(
            "INSERT INTO application_events "
            "(application_id, event_date, event_type, text, source, recorded_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (app_id, "2026-10-29", "note", "call done", "test", "2026-10-29T12:00:00+00:00"),
        )
        event_id = int(cursor.lastrowid)
        self.conn.commit()
        with self.assertRaises(state_db.StateError):
            state_db.update_application_event(
                self.conn,
                event_id=event_id,
                event_date="2026-10-28",
                application_id=app_id + 1,
            )

    def test_update_rejects_no_fields_and_invalid_stage(self):
        self.add_job()
        self.add_app()
        with self.assertRaises(state_db.StateError):
            state_db.application_update(self.conn, url="https://example.com/jobs/1")
        with self.assertRaises(state_db.StateError):
            state_db.application_update(
                self.conn,
                url="https://example.com/jobs/1",
                stages=["teleportation"],
            )

if __name__ == "__main__":
    unittest.main()
