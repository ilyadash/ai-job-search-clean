"""Tests for the Telegram bot's answer-timeout wiring.

Skipped when pydantic-settings is not installed (the dependency-free CI job);
`make test` runs them in the container.
"""
import os
import unittest
from unittest import mock

try:
    from pydantic import ValidationError

    from tools.bot_settings import load_settings
    from tools.telegram_bot import AgentRunner

    HAVE_SETTINGS = True
except ImportError:  # pragma: no cover - CI without the optional dependency
    HAVE_SETTINGS = False


@unittest.skipUnless(HAVE_SETTINGS, "pydantic-settings is not installed")
class AgentRunnerTimeout(unittest.TestCase):
    def settings(self, **env):
        values = {"PATH": os.environ.get("PATH", "")}
        values.update({key: str(value) for key, value in env.items()})
        home = {key: os.environ[key] for key in ("USERPROFILE", "HOME") if key in os.environ}
        with mock.patch.dict(os.environ, home, clear=True):
            return load_settings(values)

    def test_default_is_no_timeout(self):
        self.assertIsNone(AgentRunner(self.settings(), "{}", {}).timeout)

    def test_zero_disables_the_timeout(self):
        self.assertIsNone(
            AgentRunner(self.settings(TELEGRAM_ANSWER_TIMEOUT="0"), "{}", {}).timeout
        )

    def test_positive_timeout_is_applied(self):
        runner = AgentRunner(self.settings(TELEGRAM_ANSWER_TIMEOUT="45"), "{}", {})
        self.assertEqual(runner.timeout, 45.0)

    def test_invalid_timeout_is_an_error(self):
        with self.assertRaises(ValidationError):
            self.settings(TELEGRAM_ANSWER_TIMEOUT="soon")


if __name__ == "__main__":
    unittest.main()
