"""Guards for /add-template-cover-letter's text-only contract.

Cover letters are pasted into a portal text field: they are never compiled and
must stay `.txt`. The command exists to register a *structure and content
rules* for that text, so a careless edit could quietly reintroduce a compiler,
a PDF output, or a page limit - all of which the portal field cannot use.
These tests pin the contract, the storage layout, the activation block, and
the `/apply` wiring, so a future edit cannot drop any of them silently.
"""
import json
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
COMMAND = REPO / ".claude" / "commands" / "add-template-cover-letter.md"
APPLY = REPO / ".claude" / "commands" / "apply.md"
GUIDE = REPO / ".claude" / "skills" / "job-application-assistant" / "06-cover-letter-templates.md"
OPENCODE = REPO / "opencode.json"

# No cover-letter template ever runs one of these: the portal field is text.
COMPILE_TOOLS = ("pdflatex", "lualatex", "xelatex", "typst")


class CoverLetterTemplateIsTextOnly(unittest.TestCase):
    def setUp(self):
        self.command = COMMAND.read_text(encoding="utf-8")

    def test_command_exists_with_the_slash_title(self):
        self.assertTrue(COMMAND.exists(), f"{COMMAND} is missing")
        self.assertTrue(
            self.command.lstrip().startswith("# /add-template-cover-letter"),
            "the command file must start with a '# /add-template-cover-letter' title",
        )

    def test_never_names_a_compiler(self):
        lowered = self.command.lower()
        for tool in COMPILE_TOOLS:
            self.assertNotIn(
                tool,
                lowered,
                f"cover-letter templates have no toolchain, but the command "
                f"names {tool!r} - the artifact is plain text pasted into the "
                "portal field",
            )

    def test_stores_a_plain_txt_skeleton_and_manifest(self):
        self.assertIn("templates/cover_letters/<name>/", self.command)
        self.assertIn("template.txt", self.command)
        self.assertIn("TEMPLATE.md", self.command)
        self.assertIn("Character limit", self.command)

    def test_requires_the_textual_verification(self):
        lowered = self.command.lower()
        self.assertIn("no compile step", lowered)
        self.assertIn("word limit", lowered)
        self.assertIn("character limit", lowered)

    def test_activates_via_a_managed_block_in_the_cover_letter_guide(self):
        self.assertIn("06-cover-letter-templates.md", self.command)
        self.assertIn("BEGIN ACTIVE-TEMPLATE", self.command)
        self.assertIn("END ACTIVE-TEMPLATE", self.command)


class ApplyHonorsTheCoverLetterTemplate(unittest.TestCase):
    def setUp(self):
        self.apply = APPLY.read_text(encoding="utf-8")

    def test_apply_resolves_the_cover_letter_block(self):
        self.assertIn("/add-template-cover-letter", self.apply)
        self.assertIn("<CL_WORDS>", self.apply)
        self.assertIn("<CL_CHARS>", self.apply)
        self.assertNotIn(
            "(if any) is ignored",
            self.apply,
            "the old spec said an ACTIVE-TEMPLATE block in 06 was ignored; "
            "with the registration command that line must be gone",
        )

    def test_apply_never_checks_a_cover_letter_pdf(self):
        self.assertNotIn(
            "cover_letters/<company>/cover_<company>_<role>.pdf",
            self.apply,
            "the cover letter is never compiled, so no ./apply step may ask "
            "verify_pdf.py to read a cover-letter PDF",
        )

    def test_apply_step_5e_checks_structure_and_limits(self):
        self.assertIn("Length limits", self.apply)
        self.assertIn(
            "block order and placeholders match the active cover-letter template",
            self.apply,
        )


class GuideDocumentsTheCommand(unittest.TestCase):
    def test_cover_letter_guide_points_at_the_registration_command(self):
        self.assertIn(
            "/add-template-cover-letter",
            GUIDE.read_text(encoding="utf-8"),
            "06-cover-letter-templates.md must tell readers how to register a "
            "custom cover-letter template",
        )


class OpencodeConfigRegistersTheCommand(unittest.TestCase):
    def test_opencode_json_has_the_entry(self):
        data = json.loads(OPENCODE.read_text(encoding="utf-8"))
        entry = data["commands"].get("add-template-cover-letter")
        self.assertIsNotNone(
            entry,
            "opencode.json must register add-template-cover-letter so the "
            "command is reachable from the TUI",
        )
        self.assertIn(
            ".claude/commands/add-template-cover-letter.md",
            entry["template"],
        )


if __name__ == "__main__":
    unittest.main()
