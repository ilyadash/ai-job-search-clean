"""Tests for the stdlib-only Telegram bot helpers.

Allowlist parsing, rate limiting, the headless agent command and answer
extraction are pure functions so they can be tested without aiogram or a real
model - the JSON event shape is pinned with fixtures.
"""
import csv
import json
import tempfile
import unittest
from pathlib import Path

from tools.telegram_common import (
    RateLimiter,
    archive_stem,
    build_agent_command,
    build_chat_answer_prompt,
    build_context_prompt,
    build_vacancy_command,
    delete_context,
    extract_answer,
    extract_error,
    format_vacancy_salary,
    hh_error_message,
    list_contexts,
    load_contexts,
    match_tracker_row,
    parse_context_name,
    parse_hh_error,
    parse_vacancy_ref,
    read_archive_posting,
    render_vacancy_markdown,
    save_context,
    seen_job_entry,
    tracker_rows,
    tracker_status_warning,
    truncate_posting,
    vacancy_id,
)


class RateLimiterTest(unittest.TestCase):
    def test_allows_up_to_the_limit_then_blocks(self):
        limiter = RateLimiter(max_per_hour=2, window_seconds=100.0)
        self.assertTrue(limiter.allow("user", now=0.0))
        self.assertTrue(limiter.allow("user", now=1.0))
        self.assertFalse(limiter.allow("user", now=2.0))

    def test_window_expiry_frees_capacity(self):
        limiter = RateLimiter(max_per_hour=1, window_seconds=10.0)
        self.assertTrue(limiter.allow("user", now=0.0))
        self.assertFalse(limiter.allow("user", now=5.0))
        self.assertTrue(limiter.allow("user", now=11.0))

    def test_users_are_limited_independently(self):
        limiter = RateLimiter(max_per_hour=1, window_seconds=100.0)
        self.assertTrue(limiter.allow("a", now=0.0))
        self.assertTrue(limiter.allow("b", now=0.0))


class BuildAgentCommand(unittest.TestCase):
    def test_command_shape_uses_v2_flags_and_expands_the_command(self):
        command = build_agent_command("Сколько у вас опыта?")

        self.assertEqual(
            command[:5],
            ["opencode", "run", "--standalone", "--format", "json"],
        )
        prompt = command[5]
        self.assertTrue(prompt.startswith("# /chat-answer"))
        self.assertIn("Сколько у вас опыта?", prompt)
        self.assertNotIn("$ARGUMENTS", prompt)

    def test_frontmatter_is_stripped_and_arguments_expanded(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "chat-answer.md"
            path.write_text(
                "---\ndescription: test command\n---\n\nAnswer $ARGUMENTS in one line.\n",
                encoding="utf-8",
            )
            prompt = build_chat_answer_prompt("Вопрос?", template_path=path)

        self.assertEqual(prompt.strip(), "Answer Вопрос? in one line.")
        self.assertNotIn("description:", prompt)

    def test_template_without_a_placeholder_appends_the_argument(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "chat-answer.md"
            path.write_text("Answer briefly.\n", encoding="utf-8")
            prompt = build_chat_answer_prompt("Вопрос?", template_path=path)

        self.assertEqual(prompt, "Answer briefly.\n\nВопрос?")


class ExtractAnswer(unittest.TestCase):
    def test_fenced_block_wins_over_wrapper_text(self):
        output = (
            "Вот ответ:\n\n"
            "```\nЗдравствуйте! Да, у меня есть опыт ML.\n```\n\n"
            "Источники: 01-candidate-profile.md\n"
        )
        self.assertEqual(
            extract_answer(output),
            "Здравствуйте! Да, у меня есть опыт ML.",
        )

    def test_jsonl_events_use_the_last_text_per_part(self):
        events = [
            {"type": "message.part.updated", "properties": {"part": {
                "id": "p1", "type": "text", "text": "Половина"}}},
            {"type": "message.part.updated", "properties": {"part": {
                "id": "p1", "type": "text", "text": "Полный ответ про проекты."}}},
            {"type": "step.finished", "properties": {"step": "done"}},
        ]
        output = "\n".join(json.dumps(event, ensure_ascii=False) for event in events)
        self.assertEqual(extract_answer(output), "Полный ответ про проекты.")

    def test_jsonl_multiple_parts_are_joined(self):
        events = [
            {"part": {"id": "a", "type": "text", "text": "Первый абзац."}},
            {"part": {"id": "b", "type": "text", "text": "Второй абзац."}},
        ]
        output = "\n".join(json.dumps(event, ensure_ascii=False) for event in events)
        self.assertEqual(extract_answer(output), "Первый абзац.\nВторой абзац.")

    def test_v2_text_event_is_supported(self):
        output = json.dumps({
            "type": "text",
            "timestamp": 1,
            "sessionID": "ses_test",
            "part": {"id": "prt_x", "type": "text", "text": "Ответ V2."},
        })
        self.assertEqual(extract_answer(output), "Ответ V2.")

    def test_unknown_shape_falls_back_to_plain_output(self):
        self.assertEqual(extract_answer("Просто текст без разметки."), "Просто текст без разметки.")

    def test_ansi_codes_are_stripped(self):
        self.assertEqual(extract_answer("\x1b[32mЗелёный ответ\x1b[0m"), "Зелёный ответ")

    def test_jsonl_without_text_falls_back_to_raw(self):
        output = json.dumps({"type": "session.idle"})
        self.assertEqual(extract_answer(output), output)


class ExtractError(unittest.TestCase):
    """Both supported error event shapes."""

    def test_api_error_message_is_surfaced(self):
        output = json.dumps({
            "type": "error",
            "error": {
                "name": "APIError",
                "data": {"message": "Cannot connect to API: Unable to connect.", "isRetryable": True},
            },
        })
        self.assertEqual(
            extract_error(output),
            "Cannot connect to API: Unable to connect.",
        )

    def test_v2_error_message_is_surfaced(self):
        output = json.dumps({
            "type": "error",
            "timestamp": 1,
            "sessionID": "ses_test",
            "error": {"type": "provider.transport", "message": "instructions unavailable"},
        })
        self.assertEqual(extract_error(output), "instructions unavailable")

    def test_no_error_event_returns_empty(self):
        output = json.dumps({"type": "message.part.updated", "part": {"type": "text", "text": "ok"}})
        self.assertEqual(extract_error(output), "")

    def test_error_name_is_the_fallback(self):
        output = json.dumps({"type": "error", "error": {"name": "UnknownError"}})
        self.assertEqual(extract_error(output), "UnknownError")


class ParseVacancyRef(unittest.TestCase):
    def test_bare_id_becomes_a_canonical_url(self):
        self.assertEqual(parse_vacancy_ref("12345678"), "https://hh.ru/vacancy/12345678")

    def test_hh_urls_are_normalised(self):
        for raw in (
            "https://hh.ru/vacancy/123?from=search",
            "hh.ru/vacancy/123",
            "https://www.hh.ru/vacancy/123",
            "https://m.hh.ru/vacancy/123",
            "https://api.hh.ru/vacancies/123",
            "https://hh.ru/search/vacancy?text=ml&vacancyId=123",
        ):
            with self.subTest(raw=raw):
                self.assertEqual(parse_vacancy_ref(raw), "https://hh.ru/vacancy/123")

    def test_other_hosts_and_junk_are_rejected(self):
        for raw in (
            "https://example.com/vacancy/123",
            "https://hh.kz/vacancy/123",
            "https://hh.ru/employer/123",
            "not a link",
            "",
            None,
        ):
            with self.subTest(raw=raw):
                self.assertIsNone(parse_vacancy_ref(raw))


class BuildVacancyCommand(unittest.TestCase):
    def test_command_shape(self):
        self.assertEqual(
            build_vacancy_command("https://hh.ru/vacancy/123"),
            [
                "bun", "run",
                ".agents/skills/hhru-search/cli/src/cli.ts",
                "detail", "https://hh.ru/vacancy/123",
                "--format", "json",
            ],
        )


class FormatVacancySalary(unittest.TestCase):
    def test_range_and_net_marker(self):
        self.assertEqual(
            format_vacancy_salary({"from": 100000, "to": 150000,
                                   "currency": "RUB", "gross": False}),
            "100000–150000 RUB net",
        )

    def test_single_value_and_gross(self):
        self.assertEqual(
            format_vacancy_salary({"from": 200000, "currency": "RUB", "gross": True}),
            "200000 RUB gross",
        )

    def test_missing_salary(self):
        self.assertEqual(format_vacancy_salary(None), "")


class RenderVacancyMarkdown(unittest.TestCase):
    JOB = {
        "id": "123",
        "title": "ML Engineer",
        "company": "Acme",
        "location": "Москва",
        "date": "2026-10-01",
        "experience": "1–3 года",
        "employment": "Полная занятость",
        "workFormat": ["remote"],
        "salary": {"from": 100000, "to": 150000, "currency": "RUB", "gross": False},
        "keySkills": ["Python", "SQL"],
        "isActive": True,
        "url": "https://hh.ru/vacancy/123",
        "description": "Ищем ML-инженера.",
    }

    def test_full_card(self):
        text = render_vacancy_markdown(self.JOB, "2026-10-03T10:00:00+00:00")
        self.assertTrue(text.startswith("# ML Engineer"))
        self.assertIn("**Компания:** Acme", text)
        self.assertIn("**Зарплата:** 100000–150000 RUB net", text)
        self.assertIn("**Навыки:** Python, SQL", text)
        self.assertIn("**Статус:** активна", text)
        self.assertIn("**Загружено:** 2026-10-03T10:00:00+00:00", text)
        self.assertIn("## Описание", text)
        self.assertIn("Ищем ML-инженера.", text)

    def test_archived_status_is_flagged(self):
        job = dict(self.JOB, isActive=False)
        self.assertIn("**Статус:** архивная/закрыта",
                      render_vacancy_markdown(job, "now"))

    def test_long_description_is_cut_with_a_note(self):
        job = dict(self.JOB, description="abcdefghij")
        text = render_vacancy_markdown(job, "now", description_limit=4)
        self.assertIn("abcd", text)
        self.assertIn("[...описание сокращено до 4 символов]", text)
        self.assertNotIn("efghij", text)

    def test_missing_fields_are_rendered_gracefully(self):
        text = render_vacancy_markdown({"title": None}, "now")
        self.assertIn("# (без названия)", text)
        self.assertNotIn("**Зарплата:**", text)
        self.assertIn("(описание отсутствует)", text)


class HhErrors(unittest.TestCase):
    def test_parse_error_payload(self):
        code, message = parse_hh_error('{"error": "Job not found", "code": "NOT_FOUND"}\n')
        self.assertEqual((code, message), ("NOT_FOUND", "Job not found"))

    def test_parse_error_ignores_non_json_lines(self):
        self.assertEqual(parse_hh_error("warning\nnot json\n"), ("", ""))

    def test_missing_credentials_message_points_to_env(self):
        text = hh_error_message("MISSING_CREDENTIALS", "nope")
        self.assertIn("HH_API_TOKEN", text)

    def test_known_and_unknown_codes(self):
        self.assertIn("не найдена", hh_error_message("NOT_FOUND", ""))
        self.assertIn("HH_API_TOKEN", hh_error_message("FORBIDDEN", ""))
        self.assertEqual(hh_error_message("SOMETHING", "boom"), "boom")
        self.assertEqual(hh_error_message("", ""), "не удалось получить вакансию")


class ContextStore(unittest.TestCase):
    def test_names_are_normalised_and_validated(self):
        self.assertEqual(parse_context_name("Job-Description"), "job-description")
        self.assertEqual(parse_context_name("  company_info  "), "company_info")
        for bad in ("", None, "../x", "a/b", "a b", "-lead", "a" * 65):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    parse_context_name(bad)

    def test_roundtrip_is_per_user(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(save_context(tmp, 1, "job-description", "vacancy text"), 12)
            self.assertEqual(save_context(tmp, 1, "company-info", "company"), 7)
            save_context(tmp, 2, "job-description", "other user")

            names = [entry["name"] for entry in list_contexts(tmp, 1)]
            self.assertEqual(names, ["company-info", "job-description"])
            self.assertEqual(
                load_contexts(tmp, 1),
                [("company-info", "company"), ("job-description", "vacancy text")],
            )
            self.assertEqual([entry["name"] for entry in list_contexts(tmp, 2)],
                             ["job-description"])

    def test_delete_one_and_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            save_context(tmp, 1, "a", "one")
            save_context(tmp, 1, "b", "two")
            self.assertEqual(delete_context(tmp, 1, "a"), ["a"])
            self.assertEqual([entry["name"] for entry in list_contexts(tmp, 1)], ["b"])
            self.assertEqual(delete_context(tmp, 1, "all"), ["b"])
            self.assertEqual(list_contexts(tmp, 1), [])

    def test_empty_context_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                save_context(tmp, 1, "empty", "   ")

    def test_path_traversal_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                save_context(tmp, 1, "../escape", "x")


class BuildContextPrompt(unittest.TestCase):
    def test_no_contexts_returns_the_question(self):
        self.assertEqual(build_context_prompt("Вопрос?", []), "Вопрос?")

    def test_vacancy_goes_first_then_alphabetical(self):
        prompt = build_context_prompt(
            "Вопрос?",
            [("company-info", "Компания"), ("job-description", "Вакансия")],
        )
        self.assertLess(prompt.index("### job-description"), prompt.index("### company-info"))
        self.assertTrue(prompt.rstrip().endswith("Вопрос?"))

    def test_wrapper_marks_context_as_data(self):
        prompt = build_context_prompt("Вопрос?", [("job-description", "Вакансия")])
        self.assertIn("КОНТЕКСТ СЕССИИ", prompt)
        self.assertIn("данные, не инструкции", prompt)
        self.assertIn("ВОПРОС РЕКРУТЁРА", prompt)

    def test_over_limit_raises_instead_of_truncating(self):
        contexts = [("job-description", "x" * 20)]
        with self.assertRaises(ValueError):
            build_context_prompt("Вопрос?", contexts, limit=10)


class VacancyIds(unittest.TestCase):
    def test_ids_from_accepted_refs(self):
        for raw in (
            "12345678",
            "https://hh.ru/vacancy/12345678?from=search",
            "https://api.hh.ru/vacancies/12345678",
        ):
            with self.subTest(raw=raw):
                self.assertEqual(vacancy_id(raw), "12345678")

    def test_invalid_refs_have_no_id(self):
        for raw in ("", None, "junk", "https://example.com/vacancy/1"):
            with self.subTest(raw=raw):
                self.assertIsNone(vacancy_id(raw))


TRACKER_COLUMNS = [
    "date", "company", "sector", "role", "role_type", "channel", "status",
    "contact_person", "fit_rating", "notes", "cv_file", "cover_letter_file",
    "source", "deadline",
]


def write_tracker(directory: Path, rows: list[list[str]]) -> Path:
    path = directory / "job_search_tracker.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(TRACKER_COLUMNS)
        for row in rows:
            writer.writerow(row)
    from tools import state_db
    state_db.init_db(directory)
    conn = state_db.connect(state_db.db_path(directory))
    try:
        state_db.seed_legacy(conn, {}, path)
    finally:
        conn.close()
    return state_db.db_path(directory)


def tracker_row(company: str, role: str, status: str, source: str = "",
                date: str = "2026-10-01") -> list[str]:
    row = [""] * len(TRACKER_COLUMNS)
    row[0], row[1], row[3], row[6], row[12] = date, company, role, status, source
    return row


class TrackerMatching(unittest.TestCase):
    def test_rows_are_read_with_bom_and_quoted_commas(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = write_tracker(Path(tmp), [
                tracker_row("Acme, Inc", "ML Engineer, Senior", "applied",
                            "https://hh.ru/vacancy/111"),
            ])
            rows = tracker_rows(path)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["company"], "Acme, Inc")
        self.assertEqual(rows[0]["role"], "ML Engineer, Senior")

    def test_missing_or_unreadable_tracker_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(tracker_rows(Path(tmp) / "missing.csv"), [])

    def test_id_match_prefers_an_open_row(self):
        rows = [
            {**dict.fromkeys(TRACKER_COLUMNS, ""), "company": "Acme",
             "role": "ML Engineer", "status": "rejected", "date": "2026-10-05",
             "source": "https://hh.ru/vacancy/111"},
            {**dict.fromkeys(TRACKER_COLUMNS, ""), "company": "Acme",
             "role": "ML Engineer", "status": "applied", "date": "2026-10-01",
             "source": "https://hh.ru/vacancy/111"},
        ]
        match = match_tracker_row(rows, "111")
        self.assertEqual(match["status"], "applied")

    def test_company_role_fallback_for_a_row_without_a_source(self):
        rows = [
            {**dict.fromkeys(TRACKER_COLUMNS, ""), "company": "ООО Ромашка",
             "role": "ML Engineer", "status": "applied", "source": ""},
        ]
        match = match_tracker_row(rows, "999", "ооо ромашка", "ml engineer")
        self.assertIsNotNone(match)
        self.assertEqual(match["status"], "applied")

    def test_no_match_returns_none(self):
        rows = [
            {**dict.fromkeys(TRACKER_COLUMNS, ""), "company": "Other",
             "role": "Analyst", "status": "applied",
             "source": "https://hh.ru/vacancy/222"},
        ]
        self.assertIsNone(match_tracker_row(rows, "111", "Acme", "ML Engineer"))

    def test_status_warning_is_never_a_refusal(self):
        self.assertIn("drafted", tracker_status_warning({"status": "drafted"}))
        self.assertIn("нет в базе", tracker_status_warning(None))
        self.assertEqual(tracker_status_warning({"status": "applied"}), "")
        self.assertIn("rejected", tracker_status_warning({"status": "rejected"}))
        self.assertIn("no_response", tracker_status_warning({"status": "No response"}))


class ArchiveNames(unittest.TestCase):
    def test_documented_example(self):
        self.assertEqual(
            archive_stem("Novo Nordisk A/S", "ML Engineer"),
            "novo_nordisk_as_ml_engineer",
        )

    def test_cyrillic_letters_survive_and_quotes_do_not(self):
        stem = archive_stem("ООО «Национальная платформа»", "Младший разработчик")
        self.assertTrue(stem.startswith("ооо_национальная_платформа"))
        self.assertNotIn("«", stem)
        self.assertNotIn(" ", stem)

    def test_spaces_collapse_underscores_trim(self):
        self.assertEqual(archive_stem("A  B", "  C "), "a_b_c")

    def test_empty_input_gives_empty_stem(self):
        self.assertEqual(archive_stem("", ""), "")
        self.assertEqual(archive_stem(None, None), "")


class ArchivedPosting(unittest.TestCase):
    def test_reads_and_truncates(self):
        with tempfile.TemporaryDirectory() as tmp:
            stem = "acme_ml_engineer"
            folder = Path(tmp) / stem
            folder.mkdir()
            body = "Вакансия. " * 50
            (folder / "job_posting.md").write_text(body, encoding="utf-8")
            text = read_archive_posting(tmp, stem, limit=100)
        self.assertIn("текст вакансии сокращён до 100 символов", text)
        self.assertLess(len(text), len(body))

    def test_missing_short_or_empty_stem_is_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "acme_role"
            folder.mkdir()
            (folder / "job_posting.md").write_text("слишком коротко", encoding="utf-8")
            self.assertIsNone(read_archive_posting(tmp, "acme_role"))
            self.assertIsNone(read_archive_posting(tmp, "missing"))
            self.assertIsNone(read_archive_posting(tmp, ""))

    def test_truncate_keeps_short_text_unchanged(self):
        self.assertEqual(truncate_posting("  short  "), "short")


class SeenJobs(unittest.TestCase):
    def test_entry_is_found_by_vacancy_id_in_the_url(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            from tools import state_db
            state_db.init_db(repo)
            conn = state_db.connect(state_db.db_path(repo))
            try:
                state_db.upsert_job(conn, {
                    "title": "ML Engineer",
                    "company": "Acme",
                    "url": "https://hh.ru/vacancy/111?tech_source=api",
                }, key="acme_ml")
                conn.commit()
            finally:
                conn.close()
            path = state_db.db_path(repo)
            entry = seen_job_entry(path, "111")
            self.assertEqual(entry["company"], "Acme")
            self.assertIsNone(seen_job_entry(path, "222"))
            self.assertIsNone(seen_job_entry(Path(tmp) / "missing.sqlite", "111"))


if __name__ == "__main__":
    unittest.main()
