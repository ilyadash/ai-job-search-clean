"""Tests for the /apply tracker/archive recorder."""

import contextlib
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import apply_record as ar

try:
    from tests._candidate import SAMPLE_NAME
except ImportError:  # `python -m unittest discover -s tests` imports test modules top-level
    from _candidate import SAMPLE_NAME

HEADER = [
    "date", "company", "sector", "role", "role_type", "channel", "status",
    "contact_person", "fit_rating", "notes", "cv_file", "cover_letter_file",
    "source", "deadline",
]


def write_tracker(repo: Path, header: list[str], rows: list[dict[str, str]]) -> None:
    with (repo / "job_search_tracker.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        for row in rows:
            writer.writerow([row.get(key, "") for key in header])
    from tools import state_db
    state_db.init_db(repo)
    conn = state_db.connect(state_db.db_path(repo))
    try:
        state_db.seed_legacy(conn, {}, repo / "job_search_tracker.csv")
    finally:
        conn.close()


def read_tracker(repo: Path) -> tuple[list[str], list[dict[str, str]]]:
    from tools import state_db
    state_db.init_db(repo)
    conn = state_db.connect(state_db.db_path(repo), readonly=True)
    try:
        apps = sorted(state_db.list_applications(conn), key=lambda row: row["id"])
    finally:
        conn.close()
    rows = []
    for app in apps:
        rows.append({
            "date": str(app.get("applied_on") or str(app.get("created_at") or "")[:10]),
            "company": app.get("company") or "",
            "sector": app.get("sector") or "",
            "role": app.get("role") or "",
            "role_type": app.get("role_type") or "",
            "channel": app.get("channel") or "",
            "status": app.get("status") or "",
            "contact_person": app.get("contact_person") or "",
            "fit_rating": "" if app.get("fit_rating") is None else str(app.get("fit_rating")),
            "notes": app.get("notes") or "",
            "cv_file": app.get("cv_path") or "",
            "cover_letter_file": app.get("cover_letter_path") or "",
            "source": app.get("source_url") or "",
            "deadline": app.get("deadline") or "",
        })
    return list(HEADER), rows


def make_letter(repo: Path, text: str = f"Здравствуйте!\n\nТело письма.\n\nС уважением,\n{SAMPLE_NAME}\n") -> Path:
    path = repo / "cover_letters" / "acme" / "cover_acme_ml_engineer.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def make_posting(repo: Path, text: str = "# Vacancy\n\nFull posting text. " * 20) -> Path:
    path = repo / "posting.md"
    path.write_text(text, encoding="utf-8")
    return path


class AppendAndUpdate(unittest.TestCase):
    def test_appends_new_row_and_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            letter = make_letter(repo)
            posting = make_posting(repo)
            result = ar.record_application(
                repo,
                company="Acme",
                role="ML Engineer",
                fit=81,
                letter=str(letter),
                source="https://hh.ru/vacancy/1",
                deadline="2026-11-01",
                channel="portal",
                posting_file=str(posting),
                today="2026-10-21",
            )
            header, rows = read_tracker(repo)
            archive = repo / "documents" / "applications" / "acme_ml_engineer" / "job_posting.md"
            archive_text = archive.read_text(encoding="utf-8")

        self.assertEqual(result["action"], "appended")
        self.assertEqual(header, HEADER)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["date"], "2026-10-21")
        self.assertEqual(row["status"], "drafted")
        self.assertEqual(row["fit_rating"], "81")
        self.assertEqual(row["cv_file"], "")
        self.assertEqual(row["cover_letter_file"], letter.as_posix())
        self.assertEqual(row["source"], "https://hh.ru/vacancy/1")
        self.assertEqual(row["deadline"], "2026-11-01")
        self.assertEqual(result["archive"], "written")
        self.assertIn("Full posting text", archive_text)

    def test_source_url_resolves_company_and_role(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            letter = make_letter(repo)
            from tools import state_db
            state_db.init_db(repo)
            conn = state_db.connect(state_db.db_path(repo))
            try:
                state_db.upsert_job(conn, {
                    "title": "ML Engineer",
                    "company": "Acme",
                    "url": "https://example.com/jobs/7",
                    "status": "new",
                }, key="acme_ml")
                conn.commit()
            finally:
                conn.close()
            result = ar.record_application(
                repo,
                company="",
                role="",
                fit=80,
                letter=str(letter),
                source="https://example.com/jobs/7",
                today="2026-10-21",
            )
        self.assertEqual(result["row"]["company"], "Acme")
        self.assertEqual(result["row"]["role"], "ML Engineer")

    def test_updates_an_open_row_without_moving_it_backwards(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            letter = make_letter(repo)
            write_tracker(repo, HEADER, [{
                "date": "2026-10-01",
                "company": "ACME",
                "role": "ML Engineer",
                "status": "applied",
                "fit_rating": "70",
                "notes": "old note",
                "cv_file": "cv/old.pdf",
                "cover_letter_file": "cover_letters/old.txt",
                "source": "https://old.example/1",
                "deadline": "2026-12-01",
            }])
            result = ar.record_application(
                repo,
                company="acme",
                role="  ml   engineer ",
                fit=90,
                letter=str(letter),
                source="https://new.example/2",
                today="2026-10-21",
            )
            _, rows = read_tracker(repo)

        self.assertEqual(result["action"], "updated")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["status"], "applied")
        self.assertEqual(row["date"], "2026-10-01")
        self.assertEqual(row["cv_file"], "cv/old.pdf")
        self.assertEqual(row["fit_rating"], "90")
        self.assertEqual(row["cover_letter_file"], letter.as_posix())
        self.assertEqual(row["source"], "https://new.example/2")
        self.assertEqual(row["deadline"], "2026-12-01")
        self.assertIn("old note", row["notes"])
        self.assertIn("redrafted", row["notes"])
        self.assertEqual(result["archive"], "skipped")

    def test_drafted_row_gets_todays_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            letter = make_letter(repo)
            write_tracker(repo, HEADER, [{
                "date": "2026-10-01",
                "company": "Acme",
                "role": "ML Engineer",
                "status": "drafted",
                "cv_file": "cv/keep.pdf",
            }])
            ar.record_application(
                repo, company="Acme", role="ML Engineer", fit=80,
                letter=str(letter), today="2026-10-21",
            )
            _, rows = read_tracker(repo)
        self.assertEqual(rows[0]["date"], "2026-10-01")
        self.assertEqual(rows[0]["cv_file"], "cv/keep.pdf")

    def test_redraft_marker_is_not_duplicated(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            letter = make_letter(repo)
            write_tracker(repo, HEADER, [{
                "date": "2026-10-01",
                "company": "Acme",
                "role": "ML Engineer",
                "status": "applied",
                "notes": "old note redrafted",
            }])
            ar.record_application(
                repo, company="Acme", role="ML Engineer", fit=85,
                letter=str(letter), today="2026-10-21",
            )
            _, rows = read_tracker(repo)
        self.assertEqual(rows[0]["notes"], "old note redrafted")

    def test_final_row_gets_a_new_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            letter = make_letter(repo)
            write_tracker(repo, HEADER, [{
                "date": "2026-09-01",
                "company": "Acme",
                "role": "ML Engineer",
                "status": "rejected",
                "notes": "closed",
                "cv_file": "cv/old.pdf",
            }])
            result = ar.record_application(
                repo, company="Acme", role="ML Engineer", fit=85,
                letter=str(letter), today="2026-10-21",
            )
            _, rows = read_tracker(repo)
        self.assertEqual(result["action"], "appended")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["status"], "rejected")
        self.assertEqual(rows[1]["status"], "drafted")
        self.assertEqual(rows[1]["cv_file"], "")

    def test_legacy_header_is_migrated_without_touching_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            letter = make_letter(repo)
            legacy_header = HEADER[:-1]
            write_tracker(repo, legacy_header, [{
                "date": "2026-09-01",
                "company": "Old Co",
                "role": "Analyst",
                "status": "applied",
                "notes": "keep me",
            }])
            ar.record_application(
                repo, company="Acme", role="ML Engineer", fit=75,
                letter=str(letter), today="2026-10-21",
            )
            header, rows = read_tracker(repo)
        self.assertEqual(header, HEADER)
        self.assertEqual(rows[0]["notes"], "keep me")
        self.assertEqual(rows[0]["deadline"], "")
        self.assertEqual(len(rows), 2)

    def test_cyrillic_archive_stem(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            letter = make_letter(repo)
            posting = make_posting(repo)
            result = ar.record_application(
                repo,
                company="ЭЛТЕКС",
                role="ML Engineer / Инженер машинного обучения",
                fit=81,
                letter=str(letter),
                posting_file=str(posting),
                today="2026-10-21",
            )
        self.assertEqual(result["archive"], "written")
        self.assertEqual(
            result["archive_path"],
            "documents/applications/элтекс_ml_engineer_инженер_машинного_обучения",
        )

    def test_existing_archive_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            letter = make_letter(repo)
            posting = make_posting(repo, "new text " * 40)
            target = repo / "documents" / "applications" / "acme_ml_engineer" / "job_posting.md"
            target.parent.mkdir(parents=True)
            target.write_text("old archived text", encoding="utf-8")
            result = ar.record_application(
                repo, company="Acme", role="ML Engineer", fit=80,
                letter=str(letter), posting_file=str(posting), today="2026-10-21",
            )
            content = target.read_text(encoding="utf-8")
        self.assertEqual(result["archive"], "exists")
        self.assertEqual(content, "old archived text")

    def test_seen_jobs_is_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            letter = make_letter(repo)
            seen = repo / "job_scraper" / "seen_jobs.json"
            seen.parent.mkdir()
            seen.write_text('{"seen": {"a": {"title": "x"}}}', encoding="utf-8")
            before = seen.read_text(encoding="utf-8")
            ar.record_application(
                repo, company="Acme", role="ML Engineer", fit=80,
                letter=str(letter), today="2026-10-21",
            )
            after = seen.read_text(encoding="utf-8")
        self.assertEqual(before, after)


class Validation(unittest.TestCase):
    def test_invalid_fit(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            letter = make_letter(repo)
            for fit in (101, -1):
                with self.assertRaises(ar.RecordError):
                    ar.record_application(
                        repo, company="Acme", role="ML Engineer", fit=fit,
                        letter=str(letter),
                    )

    def test_invalid_deadline(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            letter = make_letter(repo)
            with self.assertRaises(ar.RecordError):
                ar.record_application(
                    repo, company="Acme", role="ML Engineer", fit=80,
                    letter=str(letter), deadline="2026-13-01",
                )

    def test_missing_letter_or_company(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            with self.assertRaises(ar.RecordError):
                ar.record_application(
                    repo, company="Acme", role="ML Engineer", fit=80,
                    letter=str(repo / "missing.txt"),
                )
            with self.assertRaises(ar.RecordError):
                ar.record_application(
                    repo, company="", role="ML Engineer", fit=80,
                    letter=str(make_letter(repo)),
                )

    def test_main_prints_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            letter = make_letter(repo)
            out = io.StringIO()
            with mock.patch.object(ar, "ROOT", repo), contextlib.redirect_stdout(out):
                code = ar.main([
                    "--company", "Acme",
                    "--role", "ML Engineer",
                    "--fit", "80",
                    "--letter", str(letter),
                ])
            _, rows = read_tracker(repo)
        self.assertEqual(code, 0)
        self.assertIn("ACTION: appended", out.getvalue())
        self.assertEqual(rows[0]["status"], "drafted")


if __name__ == "__main__":
    unittest.main()
