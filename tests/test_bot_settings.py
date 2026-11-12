"""Tests for the bot's typed configuration (pydantic-settings).

The repository's dependency-free CI job skips this module; `make test` runs it
inside the container, where pydantic-settings is installed.
"""
import os
import unittest
from pathlib import Path
from unittest import mock

try:
    from pydantic import ValidationError

    from tools.bot_settings import load_settings

    HAVE_PYDANTIC_SETTINGS = True
except ImportError:  # pragma: no cover - CI without the optional dependency
    HAVE_PYDANTIC_SETTINGS = False


@unittest.skipUnless(HAVE_PYDANTIC_SETTINGS, "pydantic-settings is not installed")
class BotSettingsTests(unittest.TestCase):
    def load(self, **env):
        values = {"PATH": os.environ.get("PATH", "")}
        values.update({key: str(value) for key, value in env.items()})
        # Keep the home directory: Path.home() is used to locate an env file and
        # raises on a fully cleared environment (notably on Windows).
        home = {key: os.environ[key] for key in ("USERPROFILE", "HOME") if key in os.environ}
        with mock.patch.dict(os.environ, home, clear=True):
            return load_settings(values)

    def test_defaults(self):
        settings = self.load()
        self.assertEqual(settings.token, "")
        self.assertEqual(settings.allowed_user_ids, set())
        self.assertEqual(settings.max_answers_per_hour, 30)
        self.assertEqual(settings.max_vacancies_per_hour, 5)
        self.assertIsNone(settings.answer_timeout)
        self.assertEqual(settings.effective_model(), {
            "MODEL_SERVICE": "",
            "MODEL_NAME": "",
            "MODEL_BASE_URL": "",
        })
        self.assertFalse(settings.model_api_key_configured)

    def test_allowed_user_ids_parse_commas_and_spaces(self):
        settings = self.load(TELEGRAM_ALLOWED_USER_ID=" 1, 2 3 ,4 ")
        self.assertEqual(settings.allowed_user_ids, {1, 2, 3, 4})
        self.assertEqual(
            self.load(TELEGRAM_ALLOWED_USER_ID="").allowed_user_ids, set()
        )

    def test_invalid_user_ids_fail_with_the_bad_value(self):
        for bad in ("abc", "12.5", "-5", "0", "1,@user"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValidationError) as ctx:
                    self.load(TELEGRAM_ALLOWED_USER_ID=bad)
                self.assertIn(bad, str(ctx.exception))

    def test_timeout_zero_and_negative_disable(self):
        for value in ("", "0", "0.0", "-5"):
            with self.subTest(value=value):
                self.assertIsNone(
                    self.load(TELEGRAM_ANSWER_TIMEOUT=value).answer_timeout
                )
        self.assertEqual(
            self.load(TELEGRAM_ANSWER_TIMEOUT="120").answer_timeout, 120.0
        )

    def test_invalid_timeout_fails(self):
        with self.assertRaises(ValidationError):
            self.load(TELEGRAM_ANSWER_TIMEOUT="soon")

    def test_blank_limits_use_defaults_and_zero_fails(self):
        self.assertEqual(
            self.load(TELEGRAM_MAX_ANSWERS_PER_HOUR="").max_answers_per_hour, 30
        )
        self.assertEqual(
            self.load(TELEGRAM_MAX_VACANCIES_PER_HOUR="7").max_vacancies_per_hour, 7
        )
        with self.assertRaises(ValidationError):
            self.load(TELEGRAM_MAX_ANSWERS_PER_HOUR="0")

    def test_home_override(self):
        settings = self.load(TELEGRAM_HOME="/tmp/bot-home")
        self.assertEqual(settings.home, Path("/tmp/bot-home"))

    def test_telegram_model_overrides_win(self):
        settings = self.load(
            MODEL_SERVICE="lmstudio",
            MODEL_NAME="local-model",
            TELEGRAM_MODEL_SERVICE="deepseek",
            TELEGRAM_MODEL_NAME="deepseek-chat",
        )
        self.assertEqual(settings.effective_model()["MODEL_SERVICE"], "deepseek")
        self.assertEqual(settings.effective_model()["MODEL_NAME"], "deepseek-chat")

    def test_agent_env_applies_model_overrides_to_a_base_env(self):
        settings = self.load(
            MODEL_SERVICE="lmstudio",
            TELEGRAM_MODEL_SERVICE="deepseek",
        )
        env = settings.agent_env({"PATH": "/bin"})
        self.assertEqual(env["PATH"], "/bin")
        self.assertEqual(env["MODEL_SERVICE"], "deepseek")

    def test_secrets_do_not_leak_and_api_key_precedence(self):
        settings = self.load(
            TELEGRAM_BOT_TOKEN="123:secret-token",
            MODEL_API_KEY="sk-shared",
            TELEGRAM_MODEL_API_KEY="sk-telegram",
        )
        self.assertEqual(settings.token, "123:secret-token")
        self.assertNotIn("secret-token", repr(settings))
        self.assertNotIn("sk-telegram", repr(settings))
        self.assertEqual(settings.model_overrides()["MODEL_API_KEY"], "sk-telegram")
        self.assertTrue(settings.model_api_key_configured)


if __name__ == "__main__":
    unittest.main()
