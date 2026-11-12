"""Guard for /add-template-cv's build directory rule.

The elicited LaTeX compile command redirects intermediates to `build/` and
moves the PDF back beside the source, where `/apply` reads it. Dropping the
leading `rm -f` lets a failed compile leave a stale PDF for `/apply` to
inspect; dropping the `mv` leaves no PDF beside the source at all.
"""
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ADD_TEMPLATE_CV = REPO / ".claude" / "commands" / "add-template-cv.md"

LATEX_COMMAND = (
    "rm -f <file>.pdf && mkdir -p build && lualatex -interaction=nonstopmode "
    "-output-directory=build <file>.tex && mv build/<file>.pdf ./"
)


class AddTemplateCvKeepsIntermediatesInBuild(unittest.TestCase):
    def test_latex_command_redirects_to_build_and_returns_a_fresh_pdf(self):
        self.assertIn(LATEX_COMMAND, ADD_TEMPLATE_CV.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
