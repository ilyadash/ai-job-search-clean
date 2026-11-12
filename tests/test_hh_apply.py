"""Tests for the /submit hh.ru driver (pure helpers and fail-closed paths)."""

import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import hh_apply as ha

try:
    from tests._candidate import SAMPLE_NAME
except ImportError:  # `python -m unittest discover -s tests` imports test modules top-level
    from _candidate import SAMPLE_NAME


class VacancyParsing(unittest.TestCase):
    def test_accepts_urls_ids_and_query_links(self):
        cases = {
            "https://hh.ru/vacancy/12345678": ("https://hh.ru/vacancy/12345678", "12345678"),
            "https://api.hh.ru/vacancies/12345678": ("https://hh.ru/vacancy/12345678", "12345678"),
            "https://hh.ru/vacancy/12345678?tech_source=api": (
                "https://hh.ru/vacancy/12345678",
                "12345678",
            ),
            "https://hh.ru/search/vacancy?vacancyId=12345678": (
                "https://hh.ru/vacancy/12345678",
                "12345678",
            ),
            "12345678": ("https://hh.ru/vacancy/12345678", "12345678"),
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(ha.resolve_vacancy(raw), expected)

    def test_rejects_non_hh_references(self):
        for raw in ("", "not a url", "https://example.com/jobs/1", "https://career.habr.com/vacancies/1"):
            with self.subTest(raw=raw):
                with self.assertRaises(ha.DriverError):
                    ha.resolve_vacancy(raw)


class LetterLimits(unittest.TestCase):
    def test_under_and_over_a_known_cap(self):
        self.assertIsNone(ha.letter_length_problem("abc", 5))
        self.assertIsNone(ha.letter_length_problem("abcde", 5))
        self.assertIsNotNone(ha.letter_length_problem("abcdef", 5))

    def test_no_cap_never_fails(self):
        self.assertIsNone(ha.letter_length_problem("x" * 10_000, None))
        self.assertIsNone(ha.letter_length_problem("x" * 10_000, 0))

    def test_read_letter_strips_only_the_trailing_newline(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "letter.txt"
            path.write_text(f"Здравствуйте!\n\nТело.\nС уважением,\n{SAMPLE_NAME}\n", encoding="utf-8")
            self.assertEqual(ha.read_letter(path), f"Здравствуйте!\n\nТело.\nС уважением,\n{SAMPLE_NAME}")


class ResumeSelection(unittest.TestCase):
    def test_only_resume_is_used(self):
        resumes = [{"id": "a", "title": "ML Engineer"}]
        self.assertEqual(ha.choose_resume(resumes, {})["id"], "a")

    def test_configured_id_wins(self):
        resumes = [{"id": "a", "title": "A"}, {"id": "b", "title": "B"}]
        self.assertEqual(ha.choose_resume(resumes, {"resume_id": "b"})["id"], "b")

    def test_configured_title_wins_case_insensitively(self):
        resumes = [{"id": "a", "title": "ML Engineer"}, {"id": "b", "title": "Data"}]
        self.assertEqual(
            ha.choose_resume(resumes, {"resume_title": "  ml engineer "})["id"], "a"
        )

    def test_multiple_resumes_without_config_is_ambiguous(self):
        resumes = [{"id": "a", "title": "A"}, {"id": "b", "title": "B"}]
        self.assertEqual(ha.choose_resume(resumes, {})["error"], "ambiguous")

    def test_empty_form_without_config_uses_the_default(self):
        self.assertEqual(
            ha.choose_resume([], {}),
            {"id": "", "title": "", "default": True},
        )

    def test_empty_form_with_config_is_missing(self):
        self.assertEqual(ha.choose_resume([], {"resume_id": "z"})["error"], "missing")

    def test_unmatched_config_lists_available_resumes(self):
        result = ha.choose_resume([{"id": "a", "title": "ML Engineer"}], {"resume_id": "z"})
        self.assertEqual(result["error"], "missing")
        self.assertEqual(result["available"], ["ML Engineer (a)"])


class ClassifyForm(unittest.TestCase):
    config = {"resume_id": "", "resume_title": ""}

    def make(self, **over):
        snapshot = {
            "response_button": True,
            "already_applied": False,
            "closed": False,
            "resumes": [{"id": "a", "title": "ML Engineer"}],
            "extra_fields": [],
            "cover_letter": {"required": False, "max_chars": 2000},
        }
        snapshot.update(over)
        return snapshot

    def test_ready_when_form_is_plain(self):
        decision = ha.classify_form(self.make(), self.config)
        self.assertEqual(decision["status"], "READY_FOR_APPLY")
        self.assertEqual(decision["resume"], {"id": "a", "title": "ML Engineer"})

    def test_login_required(self):
        self.assertEqual(
            ha.classify_form({"login_required": True}, self.config)["status"], "NEEDS_LOGIN"
        )

    def test_already_applied(self):
        decision = ha.classify_form(self.make(already_applied=True), self.config)
        self.assertEqual(decision["status"], "ALREADY_APPLIED")

    def test_closed_vacancy(self):
        decision = ha.classify_form(self.make(closed=True), self.config)
        self.assertEqual((decision["status"], decision["reason"]), ("ERROR", "vacancy_closed"))

    def test_missing_button_is_unexpected(self):
        decision = ha.classify_form(self.make(response_button=False), self.config)
        self.assertEqual(
            (decision["status"], decision["reason"]), ("ACTION_REQUIRED", "unexpected_form")
        )

    def test_extra_fields_block(self):
        decision = ha.classify_form(self.make(extra_fields=["Сколько лет опыта?"]), self.config)
        self.assertEqual(
            (decision["status"], decision["reason"]), ("ACTION_REQUIRED", "extra_fields")
        )
        self.assertEqual(decision["missing_fields"], ["Сколько лет опыта?"])

    def test_required_cover_letter_blocks(self):
        decision = ha.classify_form(
            self.make(cover_letter={"present": True, "required": True, "max_chars": 500}),
            self.config,
        )
        self.assertEqual(
            (decision["status"], decision["reason"]), ("ACTION_REQUIRED", "cover_letter_required")
        )
        self.assertEqual(decision["cover_letter_max"], 500)

    def test_ambiguous_and_missing_resume_block(self):
        ambiguous = ha.classify_form(
            self.make(resumes=[{"id": "a", "title": "A"}, {"id": "b", "title": "B"}]),
            self.config,
        )
        self.assertEqual(ambiguous["reason"], "resume_ambiguous")
        missing = ha.classify_form(
            self.make(resumes=[{"id": "a", "title": "ML Engineer"}]),
            {"resume_id": "z"},
        )
        self.assertEqual(missing["reason"], "resume_missing")
        self.assertEqual(missing["available_resumes"], ["ML Engineer (a)"])
        self.assertIn("ML Engineer", missing["message"])


class JsonContract(unittest.TestCase):
    def test_outcome_has_stable_keys(self):
        result = ha.outcome("APPLIED", url="u", vacancy="1", cover_letter_used="not_used")
        for key in (
            "status", "reason", "url", "vacancy_id", "resume", "cover_letter_used",
            "response_id", "attached", "missing_fields", "message", "debug",
        ):
            self.assertIn(key, result)
        self.assertEqual(result["status"], "APPLIED")

    def test_missing_session_reports_needs_login_without_playwright(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = ha.main(["check", "--url", "https://hh.ru/vacancy/1", "--json", "--repo", str(repo)])
            result = json.loads(out.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "NEEDS_LOGIN")
        self.assertEqual(result["reason"], "login_required")


class Configuration(unittest.TestCase):
    def test_env_overrides_dotenv_and_defaults_apply(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / ".env.docker").write_text(
                "HH_RESUME_TITLE=FromDotenv\nHH_HEADLESS=0\n", encoding="utf-8"
            )
            config = ha.resolve_config(env={"HH_RESUME_TITLE": "FromEnv"}, repo=repo)
            self.assertEqual(config["resume_title"], "FromEnv")
            self.assertFalse(config["headless"])
            self.assertEqual(config["storage_state"], ha.DEFAULT_STORAGE_STATE)

    def test_login_timeout_defaults_and_reads_the_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            self.assertEqual(
                ha.resolve_config(env={}, repo=repo)["login_timeout"], 300
            )
            self.assertEqual(
                ha.resolve_config(env={"HH_LOGIN_TIMEOUT": "45"}, repo=repo)["login_timeout"],
                45,
            )


class SubmitLoginHelpers(unittest.TestCase):
    def test_verify_without_storage_needs_login(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = ha.main(["verify", "--json", "--repo", tmp])
            result = json.loads(out.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "NEEDS_LOGIN")
        self.assertEqual(result["reason"], "login_required")

    def test_login_from_imports_a_valid_storage_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            source = repo / "incoming.json"
            source.write_text(
                json.dumps({"cookies": [{"name": "x", "value": "SECRET"}], "origins": []}),
                encoding="utf-8",
            )
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = ha.main(["login", "--from", "incoming.json", "--json", "--repo", tmp])
            result = json.loads(out.getvalue())
            saved = repo / "state" / "hh_storage_state.json"
            saved_exists = saved.is_file()
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "OK")
        self.assertTrue(saved_exists)
        self.assertNotIn("SECRET", out.getvalue())

    def test_login_from_rejects_a_non_storage_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "bad.json").write_text("{}", encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = ha.main(["login", "--from", "bad.json", "--json", "--repo", tmp])
            result = json.loads(out.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "ERROR")
        self.assertIn("storage_state", result["message"])

    def test_login_from_missing_file_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = ha.main(["login", "--from", "nope.json", "--json", "--repo", tmp])
            result = json.loads(out.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "ERROR")
        self.assertIn("не найден", result["message"])

    def test_login_from_accepts_origins_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            (repo / "incoming.json").write_text(
                json.dumps({"origins": [{"origin": "https://hh.ru", "localStorage": []}]}),
                encoding="utf-8",
            )
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = ha.main(["login", "--from", "incoming.json", "--json", "--repo", tmp])
            result = json.loads(out.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "OK")

    def test_account_label_ignores_generic_header_text(self):
        self.assertEqual(ha.account_label(SAMPLE_NAME), SAMPLE_NAME)
        self.assertEqual(ha.account_label("Резюме и профиль 99+"), "")
        self.assertEqual(ha.account_label("Профиль"), "")
        self.assertEqual(ha.account_label(""), "")
        self.assertEqual(ha.account_label("x" * 200), "")
        self.assertEqual(ha.account_label("  Иван\xa0Петров  "), "Иван Петров")


class Utf8Output(unittest.TestCase):
    def test_cyrillic_message_survives_a_legacy_stdout(self):
        script = Path(ha.__file__).resolve()
        env = dict(os.environ, PYTHONIOENCODING="cp1252", PYTHONUTF8="0")
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run(
                [
                    sys.executable, str(script), "check",
                    "--url", "https://hh.ru/vacancy/1", "--json", "--repo", tmp,
                ],
                env=env,
                capture_output=True,
            )
        self.assertNotIn(b"UnicodeEncodeError", proc.stderr)
        self.assertIn("нет сохранённой сессии", proc.stdout.decode("utf-8"))


class TextNormalization(unittest.TestCase):
    def test_non_breaking_space_is_handled(self):
        # hh.ru renders «Вы откликнулись» with &nbsp;, so the raw body text has \xa0.
        self.assertEqual(ha._normalize_text("Вы\xa0откликнулись"), "вы откликнулись")
        self.assertEqual(ha._normalize_text("  Отклик   отправлен "), "отклик отправлен")


class ActiveVacancyPreflight(unittest.TestCase):
    def run_check(self, repo, fetch):
        out = io.StringIO()
        with mock.patch("tools.apply_prefetch.fetch_hh", fetch):
            with contextlib.redirect_stdout(out):
                code = ha.main(
                    ["check", "--url", "https://hh.ru/vacancy/1", "--json", "--repo", str(repo)]
                )
        return code, json.loads(out.getvalue())

    def test_archived_vacancy_is_rejected_before_any_browser(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, result = self.run_check(Path(tmp), lambda *a, **k: {"archived": True})
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "ERROR")
        self.assertEqual(result["reason"], "vacancy_closed")
        self.assertIn("архив", result["message"])

    def test_missing_vacancy_404_is_rejected(self):
        def boom(*args, **kwargs):
            raise RuntimeError("hh.ru API вернул HTTP 404")

        with tempfile.TemporaryDirectory() as tmp:
            code, result = self.run_check(Path(tmp), boom)
        self.assertEqual(result["status"], "ERROR")
        self.assertEqual(result["reason"], "vacancy_closed")
        self.assertIn("не найдена", result["message"])

    def test_api_failure_falls_through_to_page_checks(self):
        def boom(*args, **kwargs):
            raise RuntimeError("network down")

        with tempfile.TemporaryDirectory() as tmp:
            code, result = self.run_check(Path(tmp), boom)
        self.assertEqual(result["status"], "NEEDS_LOGIN")

    def test_active_vacancy_falls_through(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, result = self.run_check(Path(tmp), lambda *a, **k: {"archived": False})
        self.assertEqual(result["status"], "NEEDS_LOGIN")


if __name__ == "__main__":
    unittest.main()
