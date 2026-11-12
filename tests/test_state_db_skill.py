"""Contract checks for the state-db skill, /db command, and typed tool."""

import json
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / ".claude" / "skills" / "state-db" / "SKILL.md"
SCHEMA = REPO / ".claude" / "skills" / "state-db" / "schema.md"
QUERIES = REPO / ".claude" / "skills" / "state-db" / "queries.md"
COMMAND = REPO / ".claude" / "commands" / "db.md"
PLUGIN = REPO / ".opencode" / "plugins" / "state-db.ts"


class StateDbSkillContract(unittest.TestCase):
    def test_skill_and_references_exist(self):
        for path in (SKILL, SCHEMA, QUERIES):
            self.assertTrue(path.is_file(), f"missing {path}")
        text = SKILL.read_text(encoding="utf-8")
        self.assertIn("name: state-db", text)
        self.assertIn("state_db", text)
        self.assertIn("application-show", text)
        self.assertIn("application-update", text)
        self.assertIn("application_sources", text)
        self.assertIn("v_application_current", text)
        self.assertIn("read-only", text.lower())

    def test_db_command_is_explicit_and_loads_state_skill(self):
        text = COMMAND.read_text(encoding="utf-8")
        self.assertTrue(text.lstrip().startswith("# /db"))
        for needle in ("/db show", "/db update", "/db stats", "/db query", "application_id"):
            self.assertIn(needle, text)
        config = json.loads((REPO / "opencode.json").read_text(encoding="utf-8"))
        db = config["commands"]["db"]
        self.assertIn("state-db/SKILL.md", db["template"])
        self.assertTrue(
            any(
                rule.get("action") == "shell" and "state_db.py" in rule.get("resource", "")
                for rule in config["permissions"]
            )
        )

    def test_typed_tool_has_one_action_surface(self):
        text = PLUGIN.read_text(encoding="utf-8")
        self.assertIn("Plugin.define", text)
        self.assertIn('name: "state_db"', text)
        for action in ('"show"', '"update"', '"query"', '"stats"'):
            self.assertIn(action, text)
        self.assertIn("application-update", text)
        self.assertIn("application-show", text)
        self.assertNotIn("UPDATE applications", text)
        self.assertNotIn("DELETE FROM", text)

    def test_queries_reference_are_read_only(self):
        text = QUERIES.read_text(encoding="utf-8")
        self.assertIn("SELECT", text)
        for forbidden in ("INSERT ", "UPDATE ", "DELETE ", "DROP "):
            self.assertNotIn(forbidden, text)


if __name__ == "__main__":
    unittest.main()
