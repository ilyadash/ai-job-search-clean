"""Guards for /chat-answer's honesty and safety invariants.

The command drafts answers the candidate pastes into a live AI-interviewer chat,
so the failure modes that matter are: inventing facts, losing the grounding
sources, drifting past chat-sized length, answering sensitive topics without a
warning, and treating the pasted question as instructions. These tests pin the
phrases that carry those rules so a future edit cannot quietly drop one.
"""
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
COMMAND = REPO / ".claude" / "commands" / "chat-answer.md"
FORMS = (
    REPO / ".claude" / "skills" / "job-application-assistant"
    / "08-application-forms.md"
)


class TestChatAnswerInvariants(unittest.TestCase):
    def setUp(self):
        self.text = COMMAND.read_text(encoding="utf-8")
        # Phrase checks ignore line wrapping so tests do not depend on layout.
        self.flat = " ".join(self.text.split())

    def test_command_has_the_expected_title(self):
        self.assertTrue(self.text.lstrip().startswith("# /chat-answer"))

    def test_answers_must_be_grounded_never_fabricated(self):
        self.assertIn("Never fabricate", self.flat)
        for source in ("01-candidate-profile.md", "cv/main_example.tex", "CLAUDE.md"):
            self.assertIn(source, self.flat)

    def test_length_is_chat_sized(self):
        self.assertIn("2-4 sentences", self.flat)

    def test_reuses_prepared_answers_and_style_guides(self):
        self.assertIn("07-interview-prep.md", self.flat)
        self.assertIn("03-writing-style.md", self.flat)

    def test_live_chat_rules_live_in_08(self):
        self.assertIn("08-application-forms.md", self.flat)
        self.assertIn("live chat answers", FORMS.read_text(encoding="utf-8").lower())

    def test_sensitive_topics_get_a_draft_with_warning(self):
        self.assertIn("Sensitive topics", self.flat)
        self.assertIn("Salary", self.flat)
        self.assertIn("warning", self.flat.lower())

    def test_pasted_text_is_data_not_instructions(self):
        self.assertIn("data, not instructions", self.flat)

    def test_command_is_stateless_and_never_sends(self):
        self.assertIn("Draft only", self.flat)
        self.assertIn("no side effects", self.flat)


if __name__ == "__main__":
    unittest.main()
