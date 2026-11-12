"""The database stores free-form notes; CSV quoting rules no longer apply."""

import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUTCOME = REPO / ".claude" / "commands" / "outcome.md"


class NotesAreDatabaseText(unittest.TestCase):
    def test_outcome_notes_go_through_the_database(self):
        text = OUTCOME.read_text(encoding="utf-8")
        self.assertIn("application-note", text)
        self.assertIn("application-outcome", text)
        self.assertIn("notes", text)
        self.assertNotIn("csv.DictReader", text)

    def test_no_csv_column_shift_rule(self):
        text = OUTCOME.read_text(encoding="utf-8")
        self.assertNotIn("column left", text)
        self.assertNotIn("No writer here emits a quoted tracker field", text)


if __name__ == "__main__":
    unittest.main()
