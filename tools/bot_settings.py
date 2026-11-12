#!/usr/bin/env python3
"""Typed configuration for the Telegram bot.

Only the bot imports this module; the project's other tools stay stdlib-only.
Environment variables are read once at startup and validated (no `.env` file
reading - docker compose injects them via ``env_file``). Secrets use
``SecretStr`` so they never leak into logs or repr output.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Mapping

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from tools.telegram_common import (
    DEFAULT_MAX_ANSWERS_PER_HOUR,
    DEFAULT_MAX_VACANCIES_PER_HOUR,
)


class BotSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=None,
        extra="ignore",
        case_sensitive=False,
    )

    bot_token: SecretStr | None = Field(None, validation_alias="TELEGRAM_BOT_TOKEN")
    allowed_user_ids: Annotated[set[int], NoDecode] = Field(
        default_factory=set, validation_alias="TELEGRAM_ALLOWED_USER_ID"
    )
    home: Path = Field(default_factory=Path.home, validation_alias="TELEGRAM_HOME")
    max_answers_per_hour: int = Field(
        DEFAULT_MAX_ANSWERS_PER_HOUR,
        ge=1,
        validation_alias="TELEGRAM_MAX_ANSWERS_PER_HOUR",
    )
    max_vacancies_per_hour: int = Field(
        DEFAULT_MAX_VACANCIES_PER_HOUR,
        ge=1,
        validation_alias="TELEGRAM_MAX_VACANCIES_PER_HOUR",
    )
    answer_timeout: float | None = Field(
        None, validation_alias="TELEGRAM_ANSWER_TIMEOUT"
    )

    model_service: str = Field("", validation_alias="MODEL_SERVICE")
    model_name: str = Field("", validation_alias="MODEL_NAME")
    model_base_url: str = Field("", validation_alias="MODEL_BASE_URL")
    model_api_key: SecretStr | None = Field(None, validation_alias="MODEL_API_KEY")

    telegram_model_service: str = Field("", validation_alias="TELEGRAM_MODEL_SERVICE")
    telegram_model_name: str = Field("", validation_alias="TELEGRAM_MODEL_NAME")
    telegram_model_base_url: str = Field("", validation_alias="TELEGRAM_MODEL_BASE_URL")
    telegram_model_api_key: SecretStr | None = Field(
        None, validation_alias="TELEGRAM_MODEL_API_KEY"
    )

    @field_validator("allowed_user_ids", mode="before")
    @classmethod
    def _parse_allowed_user_ids(cls, value: object) -> set[int]:
        if value is None or value == "":
            return set()
        if isinstance(value, set):
            return value
        if isinstance(value, (list, tuple)):
            chunks = [str(item) for item in value]
        elif isinstance(value, str):
            chunks = value.replace(",", " ").split()
        else:
            raise ValueError(
                "TELEGRAM_ALLOWED_USER_ID must be a comma-separated list of user ids"
            )
        allowed: set[int] = set()
        for chunk in chunks:
            try:
                user_id = int(chunk)
            except ValueError:
                raise ValueError(f"invalid Telegram user id: {chunk!r}") from None
            if user_id <= 0:
                raise ValueError(f"Telegram user ids are positive, got {user_id}")
            allowed.add(user_id)
        return allowed

    @field_validator("answer_timeout", mode="before")
    @classmethod
    def _parse_answer_timeout(cls, value: object) -> float | None:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        try:
            seconds = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            raise ValueError(f"invalid TELEGRAM_ANSWER_TIMEOUT: {value!r}") from None
        return seconds if seconds > 0 else None

    @field_validator("max_answers_per_hour", "max_vacancies_per_hour", mode="before")
    @classmethod
    def _blank_limit_uses_default(cls, value: object, info) -> object:
        if value is None or (isinstance(value, str) and not value.strip()):
            return (
                DEFAULT_MAX_ANSWERS_PER_HOUR
                if info.field_name == "max_answers_per_hour"
                else DEFAULT_MAX_VACANCIES_PER_HOUR
            )
        return value

    @field_validator("home", mode="before")
    @classmethod
    def _blank_home_uses_default(cls, value: object) -> object:
        if value is None or (isinstance(value, str) and not value.strip()):
            return Path.home()
        return value

    @field_validator(
        "model_service", "model_name", "model_base_url",
        "telegram_model_service", "telegram_model_name", "telegram_model_base_url",
        mode="before",
    )
    @classmethod
    def _strip_strings(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator(
        "bot_token", "model_api_key", "telegram_model_api_key", mode="before"
    )
    @classmethod
    def _blank_secret_is_unset(cls, value: object) -> object:
        if isinstance(value, str):
            stripped = value.strip()
            return stripped or None
        return value

    @property
    def token(self) -> str:
        return self.bot_token.get_secret_value() if self.bot_token else ""

    def effective_model(self) -> dict[str, str]:
        """The model selection the bot uses (TELEGRAM_MODEL_* wins)."""
        return {
            "MODEL_SERVICE": self.telegram_model_service or self.model_service,
            "MODEL_NAME": self.telegram_model_name or self.model_name,
            "MODEL_BASE_URL": self.telegram_model_base_url or self.model_base_url,
        }

    @property
    def model_api_key_configured(self) -> bool:
        key = self.telegram_model_api_key or self.model_api_key
        return bool(key and key.get_secret_value())

    def model_overrides(self) -> dict[str, str]:
        """MODEL_* values with the TELEGRAM_MODEL_* overrides applied."""
        overrides = {
            key: value
            for key, value in self.effective_model().items()
            if value
        }
        key = self.telegram_model_api_key or self.model_api_key
        if key and key.get_secret_value():
            overrides["MODEL_API_KEY"] = key.get_secret_value()
        return overrides

    def agent_env(self, base: Mapping[str, str] | None = None) -> dict[str, str]:
        """Process env for the agent/hh subprocesses with model overrides."""
        env = dict(os.environ if base is None else base)
        env.update(self.model_overrides())
        return env


def load_settings(env: Mapping[str, str] | None = None) -> BotSettings:
    values = dict(os.environ if env is None else env)
    return BotSettings(_env_file=None, **values)
