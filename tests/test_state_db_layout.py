"""Architecture guards for the state_db package split."""

import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CORE = REPO / "tools" / "state_db_core"
FACADE = REPO / "tools" / "state_db.py"

EXPECTED_MODULES = {
    "common.py",
    "db.py",
    "jobs.py",
    "applications.py",
    "outcomes.py",
    "migration_text.py",
    "migration_jobs.py",
    "legacy_import.py",
    "stats.py",
    "cli.py",
}

LEGACY_PRIVATE_NAMES = {
    "_application_row",
    "_band",
    "_insert_application",
    "_job_row",
    "_load_json",
    "_overall_score",
    "_set_stage",
}


class StateDbLayoutTests(unittest.TestCase):
    def test_core_modules_exist(self):
        present = {path.name for path in CORE.glob("*.py")}
        self.assertTrue(EXPECTED_MODULES <= present, EXPECTED_MODULES - present)

    def test_facade_stays_thin(self):
        self.assertLessEqual(len(FACADE.read_text(encoding="utf-8").splitlines()), 150)

    def test_core_modules_stay_bounded(self):
        oversized = {
            path.name: len(path.read_text(encoding="utf-8").splitlines())
            for path in CORE.glob("*.py")
            if len(path.read_text(encoding="utf-8").splitlines()) > 750
        }
        self.assertEqual(oversized, {})

    def test_core_does_not_import_the_facade(self):
        offenders = [
            path.name
            for path in CORE.glob("*.py")
            if "from tools.state_db import" in path.read_text(encoding="utf-8")
            or "import tools.state_db" in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(offenders, [])

    def test_facade_keeps_legacy_private_names(self):
        from tools import state_db

        for name in LEGACY_PRIVATE_NAMES:
            self.assertTrue(hasattr(state_db, name), name)
        self.assertTrue(hasattr(state_db, "main"))
        self.assertTrue(hasattr(state_db, "StateError"))

    def test_dependency_direction(self):
        jobs = (CORE / "jobs.py").read_text(encoding="utf-8")
        self.assertNotIn("from .applications", jobs)
        self.assertNotIn("from .outcomes", jobs)
        common = (CORE / "common.py").read_text(encoding="utf-8")
        self.assertNotIn("from .db", common)
        self.assertNotIn("from .jobs", common)

    def test_cli_entrypoint_still_starts(self):
        result = subprocess.run(
            [sys.executable, str(FACADE), "--help"],
            cwd=REPO,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("application-update", result.stdout)


if __name__ == "__main__":
    unittest.main()
