"""Tests for the deterministic cover-letter checker."""

import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from tools import letter_check as lc

try:
    from tests._candidate import SAMPLE_NAME, candidate_name, signature_name
except ImportError:  # `python -m unittest discover -s tests` imports test modules top-level
    from _candidate import SAMPLE_NAME, candidate_name, signature_name

GOOD_BODY = "Я работаю с речевыми и текстовыми моделями. " * 12
# The sign-off name comes from the profile, never from a hardcoded literal:
# see tests/_candidate.py. On the upstream template it falls back to SAMPLE_NAME.
SIGNATURE = signature_name(candidate_name())
GOOD = f"Здравствуйте!\n\n{GOOD_BODY.strip()}\n\nС уважением,\n{SIGNATURE}\n"


class TemplateLimits(unittest.TestCase):
    def _repo(self, tmp: str, block: str, manifest: str | None = None) -> Path:
        repo = Path(tmp)
        skill = repo / ".claude" / "skills" / "job-application-assistant"
        skill.mkdir(parents=True)
        (skill / "06-cover-letter-templates.md").write_text(
            block, encoding="utf-8"
        )
        if manifest is not None:
            manifest_path = repo / "templates" / "cover_letters" / "hh" / "TEMPLATE.md"
            manifest_path.parent.mkdir(parents=True)
            manifest_path.write_text(manifest, encoding="utf-8")
        return repo

    def test_active_block_with_manifest(self):
        block = (
            "# Guide\n\n"
            "<!-- BEGIN ACTIVE-TEMPLATE (managed) -->\n"
            "> - **Word limit:** `75-250` words of body text\n"
            "> - **Manifest:** `templates/cover_letters/hh/TEMPLATE.md`\n"
            "<!-- END ACTIVE-TEMPLATE -->\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(tmp, block, "- **Character limit:** 1200\n")
            words, chars = lc.template_limits(repo)
        self.assertEqual(words, (75, 250))
        self.assertEqual(chars, 1200)

    def test_manifest_none_is_no_cap(self):
        block = (
            "<!-- BEGIN ACTIVE-TEMPLATE -->\n"
            "> - **Word limit:** `75-250` words\n"
            "> - **Manifest:** `templates/cover_letters/hh/TEMPLATE.md`\n"
            "<!-- END ACTIVE-TEMPLATE -->\n"
        )
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(tmp, block, "- **Character limit:** none\n")
            words, chars = lc.template_limits(repo)
        self.assertEqual(words, (75, 250))
        self.assertIsNone(chars)

    def test_no_active_block_uses_stock_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(tmp, "# no block here\n")
            words, chars = lc.template_limits(repo)
        self.assertEqual(words, lc.DEFAULT_WORDS)
        self.assertIsNone(chars)

    def test_parse_word_range(self):
        self.assertEqual(lc.parse_word_range("75-250"), (75, 250))
        self.assertEqual(lc.parse_word_range("250"), (250, 250))
        with self.assertRaises(ValueError):
            lc.parse_word_range("nonsense")


class LetterChecks(unittest.TestCase):
    def check(self, text: str, **kwargs):
        kwargs.setdefault("words", (75, 250))
        return lc.check_letter(self.path(text), **kwargs)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def path(self, text: str) -> Path:
        path = self.dir / "cover.txt"
        path.write_text(text, encoding="utf-8")
        return path

    def assert_all_pass(self, findings):
        self.assertTrue(all(ok for ok, _ in findings), [m for ok, m in findings if not ok])

    def assert_fails(self, findings, fragment):
        failed = [m for ok, m in findings if not ok]
        self.assertTrue(
            any(fragment in message for message in failed),
            f"{fragment!r} not in failures: {failed}",
        )

    def test_good_letter_passes(self):
        findings = self.check(GOOD, language="ru")
        self.assert_all_pass(findings)

    def test_word_range_is_enforced(self):
        findings = self.check(GOOD, words=(100, 200))
        self.assert_fails(findings, "body words")

    def test_markup_placeholder_em_dash_and_banned_phrase_fail(self):
        for fragment, text in (
            ("markdown markup", GOOD.replace("Я работаю", "**Я** работаю")),
            ("placeholder", GOOD.replace("моделями", "моделями [VACANCY_URL]")),
            ("em-dash", GOOD.replace("моделями", "моделями —")),
            ("banned gap", GOOD.replace("моделями", "моделями. Сразу обозначу границы")),
        ):
            with self.subTest(fragment=fragment):
                self.assert_fails(self.check(text), fragment)

    def test_greeting_and_signoff_are_required(self):
        no_greeting = GOOD.replace("Здравствуйте!\n\n", "")
        self.assert_fails(self.check(no_greeting), "greeting")
        no_signoff = "Здравствуйте!\n\n" + GOOD_BODY + "\n\n" + SAMPLE_NAME + "\n"
        self.assert_fails(self.check(no_signoff), "sign-off")

    def test_signature_carries_the_profile_name(self):
        # The letter must be signed with the candidate's name, which is read
        # from the profile rather than hardcoded in this test.
        findings = self.check(GOOD, language="ru")
        signature = next(message for ok, message in findings if message.startswith("signature:"))
        self.assertIn(SIGNATURE, signature)

        # A placeholder signature does not satisfy the presence check.
        placeholder = f"Здравствуйте!\n\n{GOOD_BODY.strip()}\n\nС уважением,\n[YOUR_NAME]\n"
        findings = self.check(placeholder, language="ru")
        signature = next(message for ok, message in findings if message.startswith("signature:"))
        self.assertNotIn(SIGNATURE, signature)

    def test_character_cap_is_enforced(self):
        findings = self.check(GOOD, chars=100)
        self.assert_fails(findings, "characters")

    def test_language_mismatch_is_flagged(self):
        findings = self.check(GOOD, language="en")
        self.assert_fails(findings, "language")


class CommandLine(unittest.TestCase):
    def test_main_passes_and_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            good = Path(tmp) / "good.txt"
            good.write_text(GOOD, encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = lc.main([str(good)])
            self.assertEqual(code, 0)
            self.assertIn("RESULT: PASS", out.getvalue())

            bad = Path(tmp) / "bad.txt"
            bad.write_text(f"Здравствуйте!\n\nКоротко.\n\nС уважением,\n{SAMPLE_NAME}\n", encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = lc.main([str(bad)])
            self.assertEqual(code, 1)
            self.assertIn("RESULT: FAIL", out.getvalue())


if __name__ == "__main__":
    unittest.main()
