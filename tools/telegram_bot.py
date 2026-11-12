#!/usr/bin/env python3
"""Telegram bot: answers forwarded recruiter questions via the OpenCode agent.

Runs in its own container (see docker-compose.yml) as a long-polling aiogram
bot - no inbound ports, no Telethon session, no userbot: your Telegram account
is never touched. For every text message from an allowlisted user id it runs
the headless agent:

    opencode run --standalone --format json "<expanded /chat-answer prompt>"

with a read-only rendered OpenCode profile (files readable, no writes, no
shell, no network tools), then sends the draft answer back to the user, who
copies it into the recruiter chat. Nothing is ever sent to the recruiter. The
bot token lives only in this container; the Q&A audit lives in TELEGRAM_HOME.

Modes:
    serve    run the bot (default)
    status   print a configuration summary (no Telegram connection)

Environment: TELEGRAM_BOT_TOKEN, TELEGRAM_ALLOWED_USER_ID,
TELEGRAM_MAX_ANSWERS_PER_HOUR, TELEGRAM_MAX_VACANCIES_PER_HOUR,
TELEGRAM_ANSWER_TIMEOUT, TELEGRAM_HOME, the TELEGRAM_MODEL_* overrides
(fallbacks: MODEL_SERVICE, MODEL_NAME, MODEL_BASE_URL, MODEL_API_KEY), plus
the MODEL_* variables and MODEL_API_KEY consumed by
tools/render_opencode_config.py.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

if __package__ in (None, ""):
    # Direct script execution (python3 tools/telegram_bot.py) puts tools/ on
    # sys.path, not the repo root - add it so `tools.telegram_common` resolves
    # in the bot container.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pydantic import ValidationError

from tools.bot_settings import BotSettings, load_settings
from tools.telegram_common import (
    MAX_QUESTION_CHARS,
    VACANCY_CONTEXT,
    RateLimiter,
    archive_stem,
    build_agent_command,
    build_context_prompt,
    build_vacancy_command,
    delete_context,
    extract_answer,
    extract_error,
    format_vacancy_salary,
    hh_error_message,
    list_contexts,
    load_contexts,
    match_tracker_row,
    parse_context_name,
    parse_hh_error,
    parse_vacancy_ref,
    read_archive_posting,
    render_vacancy_markdown,
    save_context,
    seen_job_entry,
    tracker_rows,
    tracker_status_warning,
    vacancy_id,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
RENDER_CONFIG = REPO_ROOT / "tools" / "render_opencode_config.py"
REGISTRY = REPO_ROOT / "docker" / "services.json"
TRACKER_PATH = REPO_ROOT / "state" / "job_search.sqlite"
SEEN_JOBS_PATH = REPO_ROOT / "state" / "job_search.sqlite"
APPLICATIONS_DIR = REPO_ROOT / "documents" / "applications"
VACANCY_TIMEOUT_SECONDS = 30


class AgentError(Exception):
    """The headless agent run failed; the message is safe to show the user."""


def render_config(settings: BotSettings, base_env: dict) -> str:
    result = subprocess.run(
        [
            sys.executable, str(RENDER_CONFIG),
            "--registry", str(REGISTRY),
            "--profile", "readonly",
        ],
        env=settings.agent_env(base_env),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return result.stdout


def append_audit(record: dict, home_path: Path) -> None:
    path = home_path / "audit.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


async def fetch_vacancy(url: str, env: dict) -> dict:
    """Fetch one vacancy through the shipped hhru-search CLI."""
    try:
        process = await asyncio.create_subprocess_exec(
            *build_vacancy_command(url),
            cwd=str(REPO_ROOT),
            env=dict(env),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        raise AgentError("не найден bun: образ должен содержать bun (make build)") from None
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), VACANCY_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        raise AgentError(f"hh.ru не ответил за {VACANCY_TIMEOUT_SECONDS} с") from None
    out = stdout.decode("utf-8", "replace")
    err = stderr.decode("utf-8", "replace")
    if process.returncode != 0:
        code, message = parse_hh_error(err)
        raise AgentError(hh_error_message(code, message))
    try:
        payload = json.loads(out)
    except json.JSONDecodeError:
        raise AgentError("hhru-search вернул не JSON") from None
    if not isinstance(payload, dict):
        raise AgentError("hhru-search вернул неожиданный ответ")
    return payload


class AgentRunner:
    """Runs one headless agent per question, one at a time."""

    def __init__(self, settings: BotSettings, config: str, base_env: dict):
        self.settings = settings
        self.base_env = base_env
        self.config = config
        self.timeout = settings.answer_timeout
        self.semaphore = asyncio.Semaphore(1)

    async def answer(self, question: str) -> str:
        async with self.semaphore:
            command = build_agent_command(question)
            child_env = self.settings.agent_env(self.base_env)
            child_env["OPENCODE_CONFIG_CONTENT"] = self.config
            process = await asyncio.create_subprocess_exec(
                *command,
                cwd=str(REPO_ROOT),
                env=child_env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            if self.timeout is None:
                stdout, stderr = await process.communicate()
            else:
                try:
                    stdout, stderr = await asyncio.wait_for(process.communicate(), self.timeout)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
                    raise AgentError(f"агент не ответил за {self.timeout:g} с") from None
            if process.returncode != 0:
                lines = stderr.decode("utf-8", "replace").strip().splitlines()
                detail = f": {lines[-1]}" if lines else ""
                if not detail:
                    message = extract_error(stdout.decode("utf-8", "replace"))
                    detail = f": {message}" if message else ""
                raise AgentError(f"агент завершился с ошибкой{detail}")
            answer = extract_answer(stdout.decode("utf-8", "replace"))
            if not answer:
                raise AgentError("агент вернул пустой ответ")
            return answer


def build_dispatcher(allowed: set[int], runner: AgentRunner, limiter: RateLimiter,
                     vacancy_limiter: RateLimiter, settings: BotSettings,
                     base_env: dict):
    from aiogram import Dispatcher, F
    from aiogram.filters import Command, CommandObject, CommandStart
    from aiogram.types import Message

    dispatcher = Dispatcher()
    pending: dict[int, str] = {}

    def user_id_of(message: Message) -> int:
        return message.from_user.id if message.from_user else 0

    @dispatcher.message(CommandStart())
    async def on_start(message: Message) -> None:
        user_id = message.from_user.id if message.from_user else 0
        if user_id in allowed:
            await message.answer(
                f"Бот готов. Ваш id: {user_id}.\n"
                "Команды: /add-vacancy <ссылка hh.ru>, /add-context <имя>, "
                "/contexts, /clear-context <имя|all>.\n"
                "Перешлите вопрос AI-рекрутёра - пришлю черновик ответа."
            )
        else:
            await message.answer(
                f"Ваш Telegram id: {user_id}.\n"
                "Он не в allowlist: добавьте его в TELEGRAM_ALLOWED_USER_ID в .env.docker "
                "и перезапустите бота (make telegram-down && make telegram-up)."
            )

    @dispatcher.message(Command("help"))
    async def on_help(message: Message) -> None:
        if user_id_of(message) not in allowed:
            await message.answer("Нет доступа.")
            return
        await message.answer(
            "Перешлите (или вставьте текстом) вопрос AI-рекрутёра - верну черновик "
            "на 2-4 предложения по вашему профилю. Проверьте и скопируйте его в чат "
            "с рекрутёром: бот рекрутёру ничего не отправляет.\n\n"
            "Контекст ответов:\n"
            "/add-vacancy <url> - загрузить вакансию hh.ru (сохраняется как "
            f"«{VACANCY_CONTEXT}», заменяет предыдущую)\n"
            "/add-context <имя> - сохранить следующий текст как контекст\n"
            "/contexts - что сохранено\n"
            "/clear-context <имя|all> - удалить контекст"
        )

    @dispatcher.message(Command("add-vacancy"))
    async def on_add_vacancy(message: Message, command: CommandObject) -> None:
        user_id = user_id_of(message)
        if user_id not in allowed:
            await message.answer(f"Нет доступа. Ваш id: {user_id}.")
            return
        pending.pop(user_id, None)
        raw = (command.args or "").strip()
        if not raw:
            await message.answer(
                "Пришлите ссылку: /add-vacancy https://hh.ru/vacancy/12345678"
            )
            return
        url = parse_vacancy_ref(raw)
        if url is None:
            await message.answer(
                "Это не похоже на ссылку hh.ru. Формат: "
                "/add-vacancy https://hh.ru/vacancy/12345678 (или просто id)."
            )
            return
        if not vacancy_limiter.allow(str(user_id)):
            await message.answer("Слишком много загрузок вакансий за час, попробуйте позже.")
            return
        try:
            await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
        except Exception:
            pass

        vacancy_ref_id = vacancy_id(url)
        tracker = tracker_rows(TRACKER_PATH)
        row = match_tracker_row(tracker, vacancy_ref_id)
        company = (row or {}).get("company", "")
        role = (row or {}).get("role", "")
        if row is None:
            entry = seen_job_entry(SEEN_JOBS_PATH, vacancy_ref_id)
            if entry:
                company = str(entry.get("company") or "")
                role = str(entry.get("title") or "")
                row = match_tracker_row(tracker, vacancy_ref_id, company, role)
        warning = tracker_status_warning(row)
        stem = archive_stem(company, role) if (company or role) else ""
        archived = read_archive_posting(APPLICATIONS_DIR, stem) if stem else None

        if archived:
            try:
                chars = save_context(settings.home, user_id, VACANCY_CONTEXT, archived)
            except (OSError, ValueError) as exc:
                await message.answer(f"Не удалось сохранить контекст: {exc}")
                return
            fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
            archive_rel = f"documents/applications/{stem}/job_posting.md"
            append_audit({
                "ts": fetched_at,
                "type": "context_saved",
                "user_id": user_id,
                "name": VACANCY_CONTEXT,
                "source": "archive",
                "vacancy_id": vacancy_ref_id,
                "url": url,
                "archive_path": archive_rel,
                "tracker_status": (row or {}).get("status", ""),
                "chars": chars,
            }, settings.home)
            lines = [
                f"Вакансия сохранена как «{VACANCY_CONTEXT}» (заменила предыдущую).",
                f"Источник: {archive_rel} — без запроса к hh.",
                f"{role or 'вакансия'} — {company or '—'}",
            ]
            if warning:
                lines.append(warning)
            lines.append("Дальше отвечаю на вопросы с учётом этой вакансии.")
            await message.answer("\n".join(lines))
            return

        try:
            job = await fetch_vacancy(url, base_env)
        except AgentError as exc:
            append_audit({
                "ts": datetime.now(timezone.utc).isoformat(),
                "type": "vacancy_error",
                "user_id": user_id,
                "url": url,
                "error": str(exc),
            }, settings.home)
            await message.answer(f"Не получилось: {exc}")
            return
        fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        markdown = render_vacancy_markdown(job, fetched_at)
        try:
            chars = save_context(settings.home, user_id, VACANCY_CONTEXT, markdown)
        except (OSError, ValueError) as exc:
            await message.answer(f"Не удалось сохранить контекст: {exc}")
            return
        append_audit({
            "ts": fetched_at,
            "type": "context_saved",
            "user_id": user_id,
            "name": VACANCY_CONTEXT,
            "source": "hh",
            "vacancy_id": vacancy_ref_id,
            "url": url,
            "tracker_status": (row or {}).get("status", ""),
            "chars": chars,
        }, settings.home)
        salary = format_vacancy_salary(job.get("salary")) or "зарплата не указана"
        status = "активна" if job.get("isActive") else "АРХИВНАЯ/ЗАКРЫТА"
        lines = [
            f"Вакансия сохранена как «{VACANCY_CONTEXT}» (заменила предыдущую).",
            "Источник: hh.ru — в архиве проекта текста нет.",
            f"{job.get('title') or '(без названия)'} — {job.get('company') or '—'}",
            f"{salary}; статус: {status}.",
        ]
        if warning:
            lines.append(warning)
        lines.append("Дальше отвечаю на вопросы с учётом этой вакансии.")
        await message.answer("\n".join(lines))

    @dispatcher.message(Command("add-context"))
    async def on_add_context(message: Message, command: CommandObject) -> None:
        user_id = user_id_of(message)
        if user_id not in allowed:
            await message.answer(f"Нет доступа. Ваш id: {user_id}.")
            return
        pending.pop(user_id, None)
        raw = (command.args or "").strip()
        if not raw:
            await message.answer(
                "Укажите имя: /add-context job-description (или company-info)"
            )
            return
        try:
            name = parse_context_name(raw)
        except ValueError as exc:
            await message.answer(str(exc))
            return
        pending[user_id] = name
        await message.answer(f"Пришлите текст контекста «{name}» следующим сообщением.")

    @dispatcher.message(Command("contexts"))
    async def on_contexts(message: Message) -> None:
        user_id = user_id_of(message)
        if user_id not in allowed:
            await message.answer(f"Нет доступа. Ваш id: {user_id}.")
            return
        pending.pop(user_id, None)
        entries = list_contexts(settings.home, user_id)
        if not entries:
            await message.answer(
                "Контекстов нет. Добавьте вакансию: /add-vacancy <ссылка hh.ru> "
                "или текст: /add-context <имя>."
            )
            return
        lines = [f"- {entry['name']}: {entry['chars']} символов" for entry in entries]
        await message.answer("Сохранённые контексты:\n" + "\n".join(lines))

    @dispatcher.message(Command("clear-context"))
    async def on_clear_context(message: Message, command: CommandObject) -> None:
        user_id = user_id_of(message)
        if user_id not in allowed:
            await message.answer(f"Нет доступа. Ваш id: {user_id}.")
            return
        pending.pop(user_id, None)
        raw = (command.args or "").strip()
        if not raw:
            entries = list_contexts(settings.home, user_id)
            names = ", ".join(entry["name"] for entry in entries) or "пусто"
            await message.answer(f"Укажите имя или all. Сейчас: {names}")
            return
        try:
            deleted = delete_context(settings.home, user_id, raw)
        except ValueError as exc:
            await message.answer(str(exc))
            return
        if not deleted:
            await message.answer("Такого контекста нет.")
            return
        await message.answer("Удалено: " + ", ".join(deleted))

    @dispatcher.message(F.text)
    async def on_question(message: Message) -> None:
        user_id = user_id_of(message)
        if user_id not in allowed:
            await message.answer(f"Нет доступа. Ваш id: {user_id}.")
            return
        pending_name = pending.pop(user_id, None)
        if pending_name is not None:
            text = (message.text or "").strip()
            if not text:
                await message.answer("Пустой контекст, попробуйте снова: /add-context <имя>.")
                return
            try:
                chars = save_context(settings.home, user_id, pending_name, text)
            except (OSError, ValueError) as exc:
                await message.answer(f"Не удалось сохранить контекст: {exc}")
                return
            append_audit({
                "ts": datetime.now(timezone.utc).isoformat(),
                "type": "context_saved",
                "user_id": user_id,
                "name": pending_name,
                "source": "manual",
                "chars": chars,
            }, settings.home)
            await message.answer(
                f"Контекст «{pending_name}» сохранён ({chars} символов). Учту в ответах."
            )
            return
        if not limiter.allow(str(user_id)):
            await message.answer("Лимит ответов на час исчерпан, попробуйте позже.")
            return
        question = (message.text or "").strip()[:MAX_QUESTION_CHARS]
        if not question:
            await message.answer("Пришлите вопрос текстом.")
            return
        contexts = load_contexts(settings.home, user_id)
        try:
            prompt = build_context_prompt(question, contexts)
        except ValueError as exc:
            await message.answer(f"Не получилось: {exc}")
            return
        try:
            await message.bot.send_chat_action(chat_id=message.chat.id, action="typing")
        except Exception:
            pass
        try:
            answer = await runner.answer(prompt)
        except AgentError as exc:
            append_audit({
                "ts": datetime.now(timezone.utc).isoformat(),
                "type": "answer_error",
                "user_id": user_id,
                "message_id": message.message_id,
                "question": question,
                "contexts_used": [name for name, _ in contexts],
                "error": str(exc),
            }, settings.home)
            await message.answer(f"Не получилось: {exc}")
            return
        append_audit({
            "ts": datetime.now(timezone.utc).isoformat(),
            "type": "answer",
            "user_id": user_id,
            "message_id": message.message_id,
            "question": question,
            "contexts_used": [name for name, _ in contexts],
            "answer": answer,
        }, settings.home)
        await message.answer(f"Черновик (проверьте и скопируйте):\n\n{answer}")

    @dispatcher.message()
    async def on_other(message: Message) -> None:
        if message.from_user and message.from_user.id in allowed:
            await message.answer("Пришлите вопрос текстом (пересланное сообщение тоже подойдёт).")

    return dispatcher


def cmd_status(settings: BotSettings) -> int:
    allowed = settings.allowed_user_ids
    info = {
        "home": str(settings.home),
        "token_configured": bool(settings.token),
        "allowed_user_ids": sorted(allowed),
        "allowlist_error": "" if allowed else (
            "TELEGRAM_ALLOWED_USER_ID is not set (see .env.docker)"
        ),
        "model": settings.effective_model(),
        "model_api_key_configured": settings.model_api_key_configured,
        "answer_command": "chat-answer",
    }
    print(json.dumps(info, indent=2, ensure_ascii=False))
    return 0


def cmd_serve(settings: BotSettings, base_env: dict) -> int:
    from aiogram import Bot

    token = settings.token
    if not token:
        print("telegram-bot: TELEGRAM_BOT_TOKEN is not set (see .env.docker)", file=sys.stderr)
        return 2
    allowed = settings.allowed_user_ids
    if not allowed:
        print("telegram-bot: TELEGRAM_ALLOWED_USER_ID is not set (see .env.docker)",
              file=sys.stderr)
        return 2
    try:
        config = render_config(settings, base_env)
    except subprocess.CalledProcessError as exc:
        print("telegram-bot: failed to render the OpenCode config", file=sys.stderr)
        if exc.stderr:
            print(exc.stderr.strip(), file=sys.stderr)
        return 2

    runner = AgentRunner(settings, config, base_env)
    limiter = RateLimiter(settings.max_answers_per_hour)
    vacancy_limiter = RateLimiter(settings.max_vacancies_per_hour)
    dispatcher = build_dispatcher(
        allowed, runner, limiter, vacancy_limiter, settings, base_env
    )
    bot = Bot(token)
    print(f"telegram-bot: polling (users={sorted(allowed)})", flush=True)

    async def _run() -> None:
        try:
            await dispatcher.start_polling(bot)
        finally:
            await bot.session.close()

    asyncio.run(_run())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("mode", nargs="?", choices=("serve", "status"), default="serve")
    return parser


def _print_validation_errors(exc: ValidationError) -> None:
    print("telegram-bot: invalid configuration (see .env.docker):", file=sys.stderr)
    for error in exc.errors():
        location = ".".join(str(part) for part in error["loc"])
        print(f"  - {location}: {error['msg']}", file=sys.stderr)


def main(argv: list[str] | None = None, env: dict | None = None) -> int:
    args = build_parser().parse_args(argv)
    base_env = dict(os.environ if env is None else env)
    try:
        settings = load_settings(base_env)
    except ValidationError as exc:
        if args.mode == "status":
            details = [
                f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
                for error in exc.errors()
            ]
            print(json.dumps({"settings_error": details}, indent=2, ensure_ascii=False))
            return 0
        _print_validation_errors(exc)
        return 2
    if args.mode == "status":
        return cmd_status(settings)
    return cmd_serve(settings, base_env)


if __name__ == "__main__":
    sys.exit(main())
