"""Guards for the DB-backed /apply and /outcome contract."""

import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
COMMANDS = REPO / ".claude" / "commands"
APPLY = COMMANDS / "apply.md"
OUTCOME = COMMANDS / "outcome.md"
SKILL = REPO / ".claude" / "skills" / "job-application-assistant" / "SKILL.md"
DOCS_README = REPO / "documents" / "README.md"


class ApplyAndOutcomeUseTheDatabase(unittest.TestCase):
    def test_apply_uses_recorder_and_not_retired_files(self):
        text = APPLY.read_text(encoding="utf-8")
        self.assertIn("tools/apply_record.py", text)
        self.assertIn("state/job_search.sqlite", text)
        self.assertIn("cover_letter_used=unknown", text)

    def test_outcome_uses_database_and_narrative_archive(self):
        text = OUTCOME.read_text(encoding="utf-8")
        self.assertIn("tools/state_db.py application-outcome", text)
        self.assertIn("cover_letter_used", text)
        self.assertIn("first_response_date", text)
        self.assertIn("outcome.md", text)
        self.assertIn("narrative only", text)

    def test_outcome_requires_actual_cover_letter_usage(self):
        text = OUTCOME.read_text(encoding="utf-8")
        self.assertIn("Was a cover letter actually sent", text)
        self.assertIn("not_used", text)
        self.assertIn("not_required", text)
        self.assertIn("Do not infer this from the presence of a file", text)

    def test_archive_path_rule_has_one_home(self):
        outcome = OUTCOME.read_text(encoding="utf-8")
        self.assertIn("**Subfolder naming** rule in `documents/README.md`", outcome)
        self.assertIn("Never widen", outcome)
        self.assertIn("leave it", outcome)

    def test_skill_records_through_apply_step_6b(self):
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("`/apply` Step 6b", text)
        self.assertIn("`cover_letter_file`", text)
        self.assertIn("`cv_file` stays empty", text)

    def test_no_csv_reader_in_apply_workflow(self):
        for path in (APPLY, OUTCOME, SKILL):
            self.assertNotIn("csv.DictReader", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
