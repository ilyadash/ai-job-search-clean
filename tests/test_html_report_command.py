"""The optional HTML dashboard reads the state database, not the retired CSV."""

import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
COMMAND = REPO / ".claude" / "commands" / "html-report.md"


class HtmlReportCommandFileTests(unittest.TestCase):
    def test_command_file_exists_and_has_header(self):
        text = COMMAND.read_text(encoding="utf-8")
        first_line = text.lstrip().splitlines()[0]
        self.assertTrue(first_line.startswith("# /html-report"))
        self.assertGreater(len(text.strip()), 100)

    def test_reads_the_database_views(self):
        text = COMMAND.read_text(encoding="utf-8")
        self.assertIn("tools/state_db.py query", text)
        self.assertIn("v_funnel", text)
        self.assertIn("v_cover_letter", text)

    def test_database_is_canonical_for_stages(self):
        text = COMMAND.read_text(encoding="utf-8")
        self.assertIn("application_stages", text)
        self.assertIn("database is canonical", text)

    def test_keeps_offline_svg_output(self):
        text = COMMAND.read_text(encoding="utf-8")
        self.assertIn("inline", text.lower())
        self.assertIn("no external dependencies", text.lower())


if __name__ == "__main__":
    unittest.main()
