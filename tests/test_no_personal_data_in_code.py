"""Guard: the candidate's real name must not be committed into code or tests.

The repository principle is that committed code is profile-agnostic and
personal data is added at runtime by ``/setup`` (see ``templates/README.md``
and ``tests/test_placeholder_integrity.py``). This guard reads the candidate's
name from the profile and fails if it appears anywhere under the code roots.

On the upstream template (or an empty profile) there is no real name to
guard, so ``RealRepoIsClean`` skips. Personal-data locations are deliberately
outside the scanned roots: ``.claude/skills/``, ``documents/``, ``cv/``,
``cover_letters/``, ``templates/`` and the top-level ``CLAUDE.md`` are data,
not code.
"""
import tempfile
import unittest
from pathlib import Path

try:
    from tests._candidate import read_profile_name
except ImportError:  # `python -m unittest discover -s tests` imports test modules top-level
    from _candidate import read_profile_name

REPO = Path(__file__).resolve().parent.parent

# Code/spec roots that must stay profile-agnostic. Data roots are not listed,
# so the profile and the user's documents/CVs/letters are never scanned.
CODE_ROOTS = ("tests", "tools", ".opencode", ".agents", ".github", ".claude/commands")

# Vendored/dependency and cache directories that may sit under a code root.
SKIP_DIRS = {
    "node_modules",
    "__pycache__",
    ".git",
    ".venv",
    "venv",
    "build",
    "dist",
    ".mypy_cache",
    ".pytest_cache",
}


def real_name(repo: Path = REPO) -> str | None:
    """The candidate's real name, or None when the profile is a placeholder."""
    name, is_placeholder = read_profile_name(repo)
    return None if is_placeholder or not name else name


def find_leaks(repo: Path, name: str, code_roots=CODE_ROOTS) -> list[str]:
    """``path:line: text`` for every code line containing the name or surname."""
    needles = {name.strip()}
    tokens = name.split()
    if tokens:
        # Surname in the "Фамилия Имя Отчество" convention; the full name
        # needle still covers names where this is a given name instead.
        needles.add(tokens[0])
    needles.discard("")
    leaks: list[str] = []
    for root_name in code_roots:
        root = repo / root_name
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if not path.is_file() or any(part in SKIP_DIRS for part in path.parts):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            relative = path.relative_to(repo).as_posix()
            for number, line in enumerate(text.splitlines(), 1):
                if any(needle in line for needle in needles):
                    leaks.append(f"{relative}:{number}: {line.strip()}")
    return leaks


class GuardLogic(unittest.TestCase):
    """Pin the guard's own behaviour against isolated temporary repositories."""

    def _profile(self, repo: Path, name: str) -> None:
        path = repo / ".claude" / "skills" / "job-application-assistant" / "01-candidate-profile.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"# Candidate Profile\n\n- **Name:** {name}\n", encoding="utf-8")

    def _write(self, repo: Path, relative: str, text: str) -> None:
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def test_flags_the_real_name_in_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            self._profile(repo, "Тестов Тест Тестович")
            self._write(repo, "tests/test_sample.py", 'NAME = "Тестов Тест Тестович"\n')
            name = real_name(repo)
            self.assertEqual(name, "Тестов Тест Тестович")
            leaks = find_leaks(repo, name)
            self.assertEqual(len(leaks), 1, leaks)
            self.assertIn("tests/test_sample.py:1", leaks[0])

    def test_clean_code_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            self._profile(repo, "Тестов Тест Тестович")
            self._write(repo, "tests/test_sample.py", 'NAME = "Иван Иванов"\n')
            self.assertEqual(find_leaks(repo, real_name(repo)), [])

    def test_data_files_are_not_scanned(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            self._profile(repo, "Тестов Тест Тестович")
            self._write(repo, "CLAUDE.md", "# Job Application Assistant for Тестов Тест Тестович\n")
            self._write(repo, "documents/README.md", "Notes for Тестов Тест Тестович\n")
            self.assertEqual(find_leaks(repo, real_name(repo)), [])

    def test_placeholder_profile_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)
            self._profile(repo, "[YOUR_NAME]")
            self.assertIsNone(real_name(repo))


class RealRepoIsClean(unittest.TestCase):
    def test_no_real_name_in_committed_code(self):
        name = real_name(REPO)
        if name is None:
            self.skipTest("upstream/empty profile: no real name to guard")
        leaks = find_leaks(REPO, name)
        self.assertEqual(
            leaks,
            [],
            "the candidate's real name leaked into committed code; read it from "
            "the profile (tests._candidate) or use SAMPLE_NAME instead:\n"
            + "\n".join(leaks),
        )


if __name__ == "__main__":
    unittest.main()
