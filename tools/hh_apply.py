#!/usr/bin/env python3
"""Drive the hh.ru vacancy response form with Playwright for ``/submit``.

This is the deterministic half of `/submit`: it opens a vacancy under the
user's saved hh.ru session, inspects the response form, and either submits the
response (without a cover letter by default) or stops and reports what the form
requires. The orchestration half (`.claude/commands/submit.md`) reads the JSON
and decides whether to record the application.

Design constraints:
- Playwright is imported **lazily**. The pure helpers (URL parsing, form
  requirement classification, JSON contract) stay importable without a browser
  so the unit tests run in CI where Chromium is not installed.
- The session lives in a ``storage_state.json`` exported by ``login`` (run once
  on a machine with a display). Nothing here stores a password.
- Fail closed: an unexpected form returns ``ACTION_REQUIRED``, never a blind
  click. A vacancy that requires a cover letter or extra screener fields stops.
- hh.ru's DOM is third-party data. Only the panels this tool drives are read,
  and only the vacancy the caller named is ever opened.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.telegram_common import parse_vacancy_ref, vacancy_id

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_STORAGE_STATE = "state/hh_storage_state.json"
DEFAULT_DEBUG_DIR = "state/hh_debug"
DEFAULT_TIMEOUT_MS = 30000
DEFAULT_DELAY_MS = 1500
DEFAULT_LOGIN_TIMEOUT = 300
LOGIN_URL = "https://hh.ru/account/login"
HOME_URL = "https://hh.ru/"

# hh.ru renders the response control as a button or a link depending on the
# layout; both carry the same label, so one selector covers each.
RESPONSE_CONTROL = "button:has-text('Откликнуться'), a:has-text('Откликнуться'), [aria-label='Откликнуться']"

# Visible page markers that mean the vacancy is no longer accepting responses.
CLOSED_MARKERS = (
    "вакансия закрыта",
    "вакансия не найдена",
    "вакансия удалена",
    "больше не доступна",
    "снята с публикации",
    "не принимает отклики",
    "отклики закрыты",
)

# hh.ru overlays an optional "add a photo" prompt on the response form. It is a
# modal of its own (data-qa="additional-data-collector__*") that sits on top of
# the resume picker, so the driver closes it before reading the form.
PHOTO_POPUP = "[data-qa='additional-data-collector__popup-title']"
PHOTO_POPUP_CLOSE = "[data-qa='additional-data-collector__popup-close']"

STATUSES = (
    "APPLIED",
    "ALREADY_APPLIED",
    "ACTION_REQUIRED",
    "NEEDS_LOGIN",
    "NOT_APPLIED",
    "ERROR",
)
REASONS = (
    "cover_letter_required",
    "extra_fields",
    "resume_missing",
    "resume_ambiguous",
    "vacancy_closed",
    "letter_too_long",
    "response_not_editable",
    "login_required",
    "unexpected_form",
)


class DriverError(Exception):
    """A user-facing reason the browser step could not complete."""


class LoginRequired(DriverError):
    """The saved session is missing or hh.ru redirected to the login page."""


# --- Pure helpers (no browser) ----------------------------------------------


def read_dotenv(path: Path | str) -> dict[str, str]:
    """Read simple KEY=VALUE lines without executing anything."""
    values: dict[str, str] = {}
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return values
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def resolve_config(env: dict[str, str] | None = None, repo: Path | str = ROOT) -> dict:
    """Merge the process environment with ``.env.docker`` (env wins)."""
    base = Path(repo)
    dotenv = read_dotenv(base / ".env.docker")
    env = dict(os.environ if env is None else env)

    def pick(name: str, default: str = "") -> str:
        return (env.get(name) or dotenv.get(name) or default).strip()

    return {
        "storage_state": pick("HH_STORAGE_STATE", DEFAULT_STORAGE_STATE),
        "resume_title": pick("HH_RESUME_TITLE"),
        "resume_id": pick("HH_RESUME_ID"),
        "headless": pick("HH_HEADLESS", "1") not in {"0", "false", "False"},
        "timeout_ms": int(pick("HH_TIMEOUT_MS", str(DEFAULT_TIMEOUT_MS)) or DEFAULT_TIMEOUT_MS),
        "delay_ms": int(pick("HH_DELAY_MS", str(DEFAULT_DELAY_MS)) or DEFAULT_DELAY_MS),
        "login_timeout": int(
            pick("HH_LOGIN_TIMEOUT", str(DEFAULT_LOGIN_TIMEOUT)) or DEFAULT_LOGIN_TIMEOUT
        ),
        "debug_dir": pick("HH_DEBUG_DIR", DEFAULT_DEBUG_DIR),
    }


def resolve_vacancy(ref: str) -> tuple[str, str]:
    """Return ``(url, vacancy_id)`` for an hh URL/id, or raise ``DriverError``."""
    raw = (ref or "").strip()
    url = parse_vacancy_ref(raw)
    vid = vacancy_id(raw)
    if not url or not vid:
        # parse_vacancy_ref reads the query without its leading "?", so a
        # `?vacancyId=` link is the one accepted shape it misses; recover it here.
        match = re.search(r"[?&]vacancyId=(\d+)", raw)
        if match:
            vid = match.group(1)
            url = f"https://hh.ru/vacancy/{vid}"
    if not url or not vid:
        raise DriverError(
            "аргумент не hh.ru URL и не hh vacancy id: "
            f"{raw!r}"
        )
    return url, vid


def read_letter(path: str | Path) -> str:
    """Read a plain-text cover letter, stripped of a trailing newline only."""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise DriverError(f"не удалось прочитать сопроводительное: {exc}") from None
    return text.rstrip("\n")


def letter_length_problem(text: str, max_chars: int | None) -> str | None:
    """Return a reason when the letter exceeds the field cap, else None."""
    if not max_chars or max_chars <= 0:
        return None
    if len(text) <= max_chars:
        return None
    return f"сопроводительное {len(text)} символов, лимит поля {max_chars}"


def _normalize_text(value: str) -> str:
    """Collapse whitespace (including &nbsp;) and casefold for text matching.

    hh.ru renders status text with non-breaking spaces («Вы&nbsp;откликнулись»),
    so a plain substring test misses it; normalizing first fixes that.
    """
    return " ".join(str(value or "").replace("\xa0", " ").split()).casefold()


def classify_form(snapshot: dict, config: dict) -> dict:
    """Decide what a response-form snapshot means, without touching a browser.

    ``snapshot`` is the JSON a page driver produces. Every key is optional and
    absent means "not observed", which fails closed toward ``ACTION_REQUIRED``
    only when the form is genuinely unexpected.
    """
    if snapshot.get("login_required"):
        return {"status": "NEEDS_LOGIN", "reason": "login_required"}

    message = str(snapshot.get("message") or "")
    if snapshot.get("already_applied"):
        return {"status": "ALREADY_APPLIED", "reason": None, "message": message}
    if snapshot.get("closed"):
        return {"status": "ERROR", "reason": "vacancy_closed", "message": message}
    if not snapshot.get("response_button"):
        return {
            "status": "ACTION_REQUIRED",
            "reason": "unexpected_form",
            "message": message or "не нашёл кнопку отклика",
        }

    resumes = [
        item
        for item in (snapshot.get("resumes") or [])
        if isinstance(item, dict) and (item.get("id") or item.get("title"))
    ]
    resume = choose_resume(resumes, config)
    if resume.get("error") == "missing":
        available = resume.get("available") or []
        return {
            "status": "ACTION_REQUIRED",
            "reason": "resume_missing",
            "message": (
                "не нашёл выбранное резюме в форме"
                + (f"; доступны: {', '.join(available)}" if available else
                   "; форма не показала ни одного резюме")
            ),
            "available_resumes": available,
        }
    if resume.get("error") == "ambiguous":
        return {
            "status": "ACTION_REQUIRED",
            "reason": "resume_ambiguous",
            "message": ", ".join(resume.get("titles") or []),
        }

    if snapshot.get("extra_fields"):
        return {
            "status": "ACTION_REQUIRED",
            "reason": "extra_fields",
            "missing_fields": list(snapshot.get("extra_fields") or []),
        }

    cover = snapshot.get("cover_letter") or {}
    if cover.get("required"):
        return {
            "status": "ACTION_REQUIRED",
            "reason": "cover_letter_required",
            "cover_letter_max": cover.get("max_chars"),
        }

    return {
        "status": "READY_FOR_APPLY",
        "reason": None,
        "resume": {"id": resume.get("id"), "title": resume.get("title")},
        "cover_letter": {
            "required": bool(cover.get("required")),
            "max_chars": cover.get("max_chars"),
        },
        "message": message,
    }


def _resume_labels(resumes: list[dict]) -> list[str]:
    out = []
    for item in resumes:
        title = str(item.get("title") or "").strip()
        rid = str(item.get("id") or "").strip()
        out.append(f"{title} ({rid})" if title and rid else (title or rid))
    return out


def choose_resume(resumes: list[dict], config: dict) -> dict:
    """Pick the configured resume, or the only one; never guesses among many."""
    wanted_id = str(config.get("resume_id") or "").strip()
    wanted_title = str(config.get("resume_title") or "").strip().casefold()
    if not resumes:
        if wanted_id or wanted_title:
            # The user named a resume, but the form exposes none to match it
            # against: fail closed rather than submit with an unknown default.
            return {"error": "missing", "available": []}
        # No picker and no configured resume: use whatever the form pre-selects.
        return {"id": "", "title": "", "default": True}
    if wanted_id:
        for item in resumes:
            if str(item.get("id") or "") == wanted_id:
                return item
        return {"error": "missing", "available": _resume_labels(resumes)}
    if wanted_title:
        for item in resumes:
            if str(item.get("title") or "").strip().casefold() == wanted_title:
                return item
        return {"error": "missing", "available": _resume_labels(resumes)}
    if len(resumes) == 1:
        return resumes[0]
    return {"error": "ambiguous", "titles": _resume_labels(resumes)}


def outcome(
    status: str,
    *,
    reason: str | None = None,
    url: str = "",
    vacancy: str = "",
    resume: dict | None = None,
    cover_letter_used: str | None = None,
    response_id: str | None = None,
    attached: bool = False,
    missing_fields: list | None = None,
    message: str = "",
    debug: str = "",
) -> dict:
    """Build the stable JSON contract the orchestrator parses."""
    return {
        "status": status,
        "reason": reason,
        "url": url,
        "vacancy_id": vacancy,
        "resume": resume or {},
        "cover_letter_used": cover_letter_used,
        "response_id": response_id,
        "attached": bool(attached),
        "missing_fields": list(missing_fields or []),
        "message": message,
        "debug": debug,
    }


# --- Browser layer ----------------------------------------------------------


def _load_playwright():
    """Import Playwright lazily so the pure helpers work without it."""
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except ImportError as exc:  # pragma: no cover - exercised without Playwright
        raise DriverError(
            "Playwright не установлен: pip install playwright && "
            "playwright install chromium"
        ) from exc
    return sync_playwright


def _storage_state_path(config: dict, repo: Path) -> Path:
    path = Path(config["storage_state"])
    return path if path.is_absolute() else repo / path


def _debug_artifact(config: dict, repo: Path, page, vid: str, mode: str) -> str:
    """Save a screenshot and DOM dump for a failed run; return its directory."""
    folder = Path(config["debug_dir"])
    if not folder.is_absolute():
        folder = repo / folder
    folder.mkdir(parents=True, exist_ok=True)
    from datetime import datetime, timezone

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = folder / f"{stamp}-{vid}-{mode}"
    try:
        page.screenshot(path=str(base.with_suffix(".png")), full_page=True)
        base.with_suffix(".html").write_text(page.content(), encoding="utf-8")
    except Exception:  # pragma: no cover - best effort diagnostics only
        return ""
    try:
        return base.relative_to(repo).as_posix()
    except ValueError:
        return str(base)


def _new_context(browser, storage_state: Path, timeout_ms: int = DEFAULT_TIMEOUT_MS):
    context = browser.new_context(storage_state=str(storage_state))
    context.set_default_timeout(timeout_ms)
    return context


def _is_login_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    host = (parsed.hostname or "").lower()
    return "hh.ru" in host and "/account/login" in (parsed.path or "")


# The header control that only exists for a signed-in visitor. hh.ru swaps the
# "войти" link for this profile/resume entry once the session is valid.
LOGGED_IN_CONTROL = (
    "[data-qa='profileAndResumes-button'], [data-qa='mainmenu_profileAndResumes']"
)

# Text the profile control shows instead of an account name. Reporting
# «Резюме и профиль 99+» as the account would be worse than saying nothing.
ACCOUNT_NOISE = ("резюме и профиль", "профиль", "резюме", "войти", "вход")


def account_label(raw: str) -> str:
    """Return an informative account label, or "" when the text is generic."""
    text = " ".join(str(raw or "").replace("\xa0", " ").split())
    if not text or len(text) > 80:
        return ""
    lowered = text.casefold()
    if any(noise in lowered for noise in ACCOUNT_NOISE):
        return ""
    return text


def _logged_in(page) -> bool:  # pragma: no cover - browser only
    """True when the page shows the signed-in header control."""
    try:
        return page.query_selector(LOGGED_IN_CONTROL) is not None
    except Exception:
        return False


def _navigate_vacancy(context, url: str):
    page = context.new_page()
    page.goto(url, wait_until="domcontentloaded")
    if _is_login_url(page.url):
        raise LoginRequired("hh.ru открыл страницу входа: сессия недействительна")
    return page


def page_state(page) -> dict:  # pragma: no cover - browser only
    """Read the page before opening the form: applied/closed/button/login."""
    body = _normalize_text(page.inner_text("body"))
    return {
        "login_required": _is_login_url(page.url),
        "already_applied": "вы откликнулись" in body or "отклик отправлен" in body,
        "closed": any(marker in body for marker in CLOSED_MARKERS),
        "response_button": page.locator(RESPONSE_CONTROL).count() > 0,
    }


def open_response_form(page) -> None:  # pragma: no cover - browser only
    """Click the page's response button once to reveal the form."""
    control = page.locator(RESPONSE_CONTROL)
    if control.count() > 0:
        control.first.click()
        page.wait_for_timeout(800)


def snapshot_form(page) -> dict:  # pragma: no cover - browser only
    """Read the response panel into the plain dict ``classify_form`` consumes."""
    return {
        "resumes": _snapshot_resumes(page),
        "extra_fields": _snapshot_extra_fields(page),
        "cover_letter": _snapshot_cover_letter(page),
    }


def snapshot_response_form(page) -> dict:  # pragma: no cover - browser only
    """State before the click, then the form after it, merged for classify_form."""
    if not dismiss_overlays(page):
        return {
            "login_required": False,
            "already_applied": False,
            "closed": False,
            "response_button": False,
            "message": "не удалось закрыть окно «Добавьте фото» на hh.ru",
        }
    state = page_state(page)
    if state["response_button"]:
        open_response_form(page)
        dismiss_overlays(page)
    return {**state, **snapshot_form(page)}


def dismiss_overlays(page) -> bool:  # pragma: no cover - browser only
    """Close hh.ru's optional "add a photo" prompt; True when the page is clear.

    hh.ru stacks this prompt over the response form, so the resume picker stays
    unreadable until it is dismissed. The prompt may already be gone (the user
    dismissed it in the saved session), in which case this is a no-op.
    """
    for _ in range(4):
        close = page.query_selector(PHOTO_POPUP_CLOSE)
        if close is None:
            return True
        try:
            close.click()
        except Exception:
            return False
        page.wait_for_timeout(500)
    return page.query_selector(PHOTO_POPUP_CLOSE) is None


def _panel(page):  # pragma: no cover - browser only
    """Scope reads to the response dialog, never the "add a photo" prompt."""
    try:
        dialogs = page.query_selector_all("[role='dialog']")
    except Exception:
        dialogs = []
    candidates = []
    for dialog in dialogs:
        try:
            if dialog.query_selector("[data-qa^='additional-data-collector']") is not None:
                continue
        except Exception:
            continue
        candidates.append(dialog)
    return candidates[-1] if candidates else page


def _snapshot_resumes(page) -> list[dict]:  # pragma: no cover - browser only
    panel = _panel(page)
    selectors = [
        "[data-qa*='resume'] option",
        "select[name*='resume'] option",
    ]
    for selector in selectors:
        options = panel.query_selector_all(selector)
        if options:
            results = []
            for option in options:
                title = (option.inner_text() or "").strip()
                value = option.get_attribute("value") or ""
                if title or value:
                    results.append({"id": value, "title": title})
            if results:
                return results
    for selector in ("[role='radiogroup'] [role='radio']", "[role='radio']"):
        radios = panel.query_selector_all(selector)
        results = []
        for radio in radios:
            text = (radio.inner_text() or "").strip()
            if text:
                results.append({"id": "", "title": text})
        if results:
            return results
    # Last resort: a form that shows the already-selected resume as text with no
    # picker. Its id is not exposed, so an HH_RESUME_ID match cannot succeed;
    # the error then lists the title for HH_RESUME_TITLE instead. Footer/nav
    # links like `footer_expertresume` and `mainmenu_createResume` also carry
    # "resume" in their data-qa, so they are excluded explicitly - otherwise the
    # driver reports site navigation as if it were the user's resumes.
    results = []
    seen = set()
    noise_prefixes = ("footer_", "mainmenu_", "profileandresumes", "header_", "nav")
    for element in panel.query_selector_all("[data-qa*='resume'], [data-qa*='Resume']"):
        qa = (element.get_attribute("data-qa") or "").casefold()
        if qa.startswith(noise_prefixes):
            continue
        try:
            if element.evaluate("e => !!e.closest('footer, nav, header')"):
                continue
        except Exception:
            pass
        text = (element.inner_text() or "").strip()
        if text and len(text) <= 120 and text not in seen:
            seen.add(text)
            results.append({"id": "", "title": text})
    return results


def _field_label(element) -> str:
    return (
        (element.get_attribute("name") or "").strip()
        or (element.get_attribute("data-qa") or "").strip()
        or (element.get_attribute("placeholder") or "").strip()
        or "поле"
    )


def _is_resume_control(element) -> bool:
    label = " ".join(
        filter(
            None,
            (
                element.get_attribute("name"),
                element.get_attribute("data-qa"),
                element.get_attribute("placeholder"),
            ),
        )
    ).casefold()
    return "resume" in label or "резюме" in label


def _snapshot_extra_fields(page) -> list[str]:  # pragma: no cover - browser only
    """Screener fields beyond the first textarea (the cover letter).

    The response form's first textarea is the cover-letter field; any further
    visible textarea, and any visible free-text input, is a screener/extra field
    the driver must not fill. A single textarea is never flagged here, so a plain
    vacancy does not stop on its own cover-letter box.
    """
    panel = _panel(page)
    textareas = [item for item in panel.query_selector_all("textarea") if item.is_visible()]
    fields = [_field_label(item) for item in textareas[1:]]
    fields += [
        _field_label(item)
        for item in panel.query_selector_all("input[type='text']")
        if item.is_visible() and not _is_resume_control(item)
    ]
    return fields


def _snapshot_cover_letter(page) -> dict:  # pragma: no cover - browser only
    area = _panel(page).query_selector("textarea")
    if area is None:
        return {}
    max_chars = area.get_attribute("maxlength")
    label = (area.get_attribute("placeholder") or "") + " " + (area.get_attribute("name") or "")
    required = area.get_attribute("required") is not None or "обязательно" in label.casefold()
    return {
        "present": True,
        "required": required,
        "max_chars": int(max_chars) if max_chars and max_chars.isdigit() else None,
    }


def _submit_response(page, resume: dict, letter: str | None) -> None:  # pragma: no cover
    """Select the resume, paste the letter, and click the submit button."""
    panel = _panel(page)
    resume_id = str(resume.get("id") or "")
    if resume_id:
        select = panel.query_selector("[data-qa='resume-select'], select[name*='resume']")
        if select is not None:
            try:
                select.select_option(value=resume_id)
            except Exception:
                pass
    if letter:
        area = panel.query_selector("textarea")
        if area is not None:
            area.fill(letter)
    controls = panel.query_selector_all(RESPONSE_CONTROL)
    if controls:
        controls[-1].click()


def capture_response_id(page) -> str | None:  # pragma: no cover - browser only
    """Read the negotiation id from the URL or the response block, best effort."""
    match = re.search(r"/negotiations?/(\d+)", page.url)
    if match:
        return match.group(1)
    link = page.query_selector("a[href*='/negotiations/']")
    if link:
        match = re.search(r"/negotiations?/(\d+)", link.get_attribute("href") or "")
        if match:
            return match.group(1)
    return None


def check_active_vacancy(
    ref: str, repo: Path, env: dict[str, str] | None = None, timeout: int = 30
) -> str | None:
    """Ask the hh API whether the vacancy is archived or missing.

    Returns "archived", "missing", "active", or None when the API cannot answer
    (no token, network, 403). None never blocks: the page's own closed-vacancy
    markers remain the fallback.
    """
    try:
        from tools.apply_prefetch import fetch_hh
    except Exception:  # pragma: no cover - import guard
        return None
    try:
        _, vid = resolve_vacancy(ref)
        raw = fetch_hh(
            vid,
            Path(repo),
            dict(env if env is not None else os.environ),
            timeout,
        )
    except Exception as exc:
        if "404" in str(exc):
            return "missing"
        return None
    if not isinstance(raw, dict):
        return None
    return "archived" if raw.get("archived") else "active"


def _inactive_outcome(active: str, url: str, vid: str) -> dict:
    message = (
        "hh.ru API: вакансия не найдена или удалена"
        if active == "missing"
        else "hh.ru API: вакансия в архиве или закрыта"
    )
    return outcome("ERROR", reason="vacancy_closed", url=url, vacancy=vid, message=message)


# --- Modes ------------------------------------------------------------------


def run_check(ref: str, config: dict, repo: Path) -> dict:  # pragma: no cover
    url, vid = resolve_vacancy(ref)
    active = check_active_vacancy(ref, repo)
    if active in {"archived", "missing"}:
        return _inactive_outcome(active, url, vid)
    storage = _storage_state_path(config, repo)
    if not storage.is_file():
        return outcome(
            "NEEDS_LOGIN",
            reason="login_required",
            url=url,
            vacancy=vid,
            message=(
                "нет сохранённой сессии: выполните `python tools/hh_apply.py login` "
                "на машине с дисплеем"
            ),
        )
    sync_playwright = _load_playwright()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=config["headless"],
            chromium_sandbox=False,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        try:
            context = _new_context(browser, storage, config["timeout_ms"])
            page = _navigate_vacancy(context, url)
            snapshot = snapshot_response_form(page)
            decision = classify_form(snapshot, config)
            decision.setdefault("url", url)
            decision.setdefault("vacancy_id", vid)
            if decision["status"] in {"ACTION_REQUIRED", "ERROR"}:
                decision["debug"] = _debug_artifact(config, repo, page, vid, "check")
            return decision
        except LoginRequired as exc:
            return outcome(
                "NEEDS_LOGIN",
                reason="login_required",
                url=url,
                vacancy=vid,
                message=str(exc),
            )
        finally:
            browser.close()


def run_apply(ref: str, config: dict, repo: Path, letter_path: str | None) -> dict:  # pragma: no cover
    url, vid = resolve_vacancy(ref)
    active = check_active_vacancy(ref, repo)
    if active in {"archived", "missing"}:
        return _inactive_outcome(active, url, vid)
    storage = _storage_state_path(config, repo)
    if not storage.is_file():
        return outcome(
            "NEEDS_LOGIN",
            reason="login_required",
            url=url,
            vacancy=vid,
            message="нет сохранённой сессии: выполните login на машине с дисплеем",
        )
    letter = None
    if letter_path:
        letter = read_letter(letter_path)
    sync_playwright = _load_playwright()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=config["headless"],
            chromium_sandbox=False,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        try:
            context = _new_context(browser, storage, config["timeout_ms"])
            page = _navigate_vacancy(context, url)
            snapshot = snapshot_response_form(page)
            decision = classify_form(snapshot, config)
            if decision["status"] == "ALREADY_APPLIED":
                decision["url"] = url
                decision["vacancy_id"] = vid
                return decision
            if decision["status"] != "READY_FOR_APPLY":
                decision["url"] = url
                decision["vacancy_id"] = vid
                decision["debug"] = _debug_artifact(config, repo, page, vid, "apply")
                return decision
            max_chars = (decision.get("cover_letter") or {}).get("max_chars")
            if letter is not None:
                problem = letter_length_problem(letter, max_chars)
                if problem:
                    return outcome(
                        "ERROR",
                        reason="letter_too_long",
                        url=url,
                        vacancy=vid,
                        message=problem,
                    )
            page.wait_for_timeout(config["delay_ms"])
            _submit_response(page, decision.get("resume") or {}, letter)
            page.wait_for_timeout(800)
            body = _normalize_text(page.inner_text("body"))
            if "вы откликнулись" not in body and "отклик отправлен" not in body:
                return outcome(
                    "ACTION_REQUIRED",
                    reason="unexpected_form",
                    url=url,
                    vacancy=vid,
                    debug=_debug_artifact(config, repo, page, vid, "apply"),
                    message="после нажатия не увидел подтверждения отклика",
                )
            context.storage_state(path=str(storage))
            cover_used = "used" if letter else (
                "not_required" if not snapshot.get("cover_letter") else "not_used"
            )
            return outcome(
                "APPLIED",
                url=url,
                vacancy=vid,
                resume=decision.get("resume") or {},
                cover_letter_used=cover_used,
                response_id=capture_response_id(page),
                message="Отклик отправлен",
            )
        except LoginRequired as exc:
            return outcome(
                "NEEDS_LOGIN",
                reason="login_required",
                url=url,
                vacancy=vid,
                message=str(exc),
            )
        finally:
            browser.close()


def run_attach(ref: str, config: dict, repo: Path, letter_path: str) -> dict:  # pragma: no cover
    url, vid = resolve_vacancy(ref)
    active = check_active_vacancy(ref, repo)
    if active in {"archived", "missing"}:
        return _inactive_outcome(active, url, vid)
    storage = _storage_state_path(config, repo)
    if not storage.is_file():
        return outcome(
            "NEEDS_LOGIN",
            reason="login_required",
            url=url,
            vacancy=vid,
            message="нет сохранённой сессии: выполните login на машине с дисплеем",
        )
    letter = read_letter(letter_path)
    sync_playwright = _load_playwright()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=config["headless"],
            chromium_sandbox=False,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        try:
            context = _new_context(browser, storage, config["timeout_ms"])
            page = _navigate_vacancy(context, url)
            page.wait_for_timeout(800)
            dismiss_overlays(page)
            body = _normalize_text(page.inner_text("body"))
            if "вы откликнулись" not in body and "отклик отправлен" not in body:
                return outcome(
                    "ACTION_REQUIRED",
                    reason="unexpected_form",
                    url=url,
                    vacancy=vid,
                    message="не нашёл отправленный отклик на этой вакансии",
                )
            # hh.ru exposes an "edit/add cover letter" link on submitted
            # responses only when the employer allows it; fail closed otherwise.
            edit = page.query_selector(
                "[data-qa='negotiation-edit'], a:has-text('Дописать сопроводительное'), "
                "a:has-text('Редактировать')"
            )
            if edit is None:
                return outcome(
                    "ACTION_REQUIRED",
                    reason="response_not_editable",
                    url=url,
                    vacancy=vid,
                    message=(
                        "hh.ru не даёт дописать сопроводительное к этому отклику "
                        "(или изменился интерфейс)"
                    ),
                )
            edit.click()
            page.wait_for_timeout(800)
            area = page.locator("textarea").first
            max_chars = area.get_attribute("maxlength")
            problem = letter_length_problem(
                letter, int(max_chars) if max_chars and max_chars.isdigit() else None
            )
            if problem:
                return outcome(
                    "ERROR",
                    reason="letter_too_long",
                    url=url,
                    vacancy=vid,
                    message=problem,
                )
            area.fill(letter)
            page.get_by_role("button", name="Сохранить").last.click()
            page.wait_for_timeout(800)
            context.storage_state(path=str(storage))
            return outcome(
                "APPLIED",
                url=url,
                vacancy=vid,
                cover_letter_used="used",
                attached=True,
                response_id=capture_response_id(page),
                message="Сопроводительное добавлено к отклику",
            )
        except LoginRequired as exc:
            return outcome(
                "NEEDS_LOGIN",
                reason="login_required",
                url=url,
                vacancy=vid,
                message=str(exc),
            )
        finally:
            browser.close()


def run_status(ref: str, config: dict, repo: Path) -> dict:  # pragma: no cover
    url, vid = resolve_vacancy(ref)
    active = check_active_vacancy(ref, repo)
    if active in {"archived", "missing"}:
        return _inactive_outcome(active, url, vid)
    storage = _storage_state_path(config, repo)
    if not storage.is_file():
        return outcome(
            "NEEDS_LOGIN", reason="login_required", url=url, vacancy=vid
        )
    sync_playwright = _load_playwright()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=config["headless"],
            chromium_sandbox=False,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        try:
            context = _new_context(browser, storage, config["timeout_ms"])
            page = _navigate_vacancy(context, url)
            page.wait_for_timeout(500)
            dismiss_overlays(page)
            body = _normalize_text(page.inner_text("body"))
            if "вы откликнулись" in body or "отклик отправлен" in body:
                return outcome("ALREADY_APPLIED", url=url, vacancy=vid)
            if "вакансия закрыта" in body:
                return outcome("ERROR", reason="vacancy_closed", url=url, vacancy=vid)
            return outcome("NOT_APPLIED", url=url, vacancy=vid)
        except LoginRequired as exc:
            return outcome(
                "NEEDS_LOGIN", reason="login_required", url=url, vacancy=vid,
                message=str(exc),
            )
        finally:
            browser.close()


def run_login(config: dict, repo: Path) -> dict:  # pragma: no cover
    """Open a headed browser, wait for a real login, then save the state.

    The wait is a page poll rather than ``input()``: the agent's shell has no
    TTY, so ``input()`` returns EOF immediately and would save an empty
    session. A fresh context also lets the user sign in as a different account
    and overwrite the previous file.
    """
    storage = _storage_state_path(config, repo)
    storage.parent.mkdir(parents=True, exist_ok=True)
    sync_playwright = _load_playwright()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=False,
            chromium_sandbox=False,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        try:
            context = browser.new_context()
            page = context.new_page()
            page.goto(LOGIN_URL, wait_until="domcontentloaded")
            print(
                "Войдите в hh.ru в открытом окне (пароль/капча/2FA/SMS). "
                "Скрипт сам сохранит сессию после входа.",
                file=sys.stderr,
            )
            deadline = time.monotonic() + config["login_timeout"]
            while time.monotonic() < deadline:
                try:
                    if page.is_closed():
                        break
                    if not _is_login_url(page.url) and _logged_in(page):
                        break
                except Exception:
                    break
                try:
                    page.wait_for_timeout(1000)
                except Exception:
                    break
            try:
                signed_in = not page.is_closed() and (
                    not _is_login_url(page.url) and _logged_in(page)
                )
            except Exception:
                signed_in = False
            if not signed_in:
                return outcome(
                    "ERROR",
                    reason="login_required",
                    message=(
                        "вход не завершён за отведённое время "
                        f"({config['login_timeout']} с): сессия не сохранена, повторите login"
                    ),
                )
            try:
                context.storage_state(path=str(storage))
            except Exception as exc:
                return outcome(
                    "ERROR",
                    reason="login_required",
                    message=(
                        "вход выполнен, но сохранить сессию не удалось "
                        f"({exc}); не закрывайте окно до сообщения об успехе и повторите login"
                    ),
                )
            return outcome("OK", message=f"сессия сохранена: {storage}")
        finally:
            browser.close()


def run_verify(config: dict, repo: Path) -> dict:  # pragma: no cover
    """Check the saved session without sending anything."""
    storage = _storage_state_path(config, repo)
    if not storage.is_file():
        return outcome(
            "NEEDS_LOGIN",
            reason="login_required",
            message=f"нет сохранённой сессии ({config['storage_state']}): выполните login",
        )
    sync_playwright = _load_playwright()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            chromium_sandbox=False,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        try:
            try:
                context = _new_context(browser, storage, config["timeout_ms"])
            except Exception as exc:
                return outcome(
                    "NEEDS_LOGIN",
                    reason="login_required",
                    message=f"сохранённая сессия не читается ({exc}): выполните login заново",
                )
            page = context.new_page()
            try:
                page.goto(HOME_URL, wait_until="domcontentloaded")
            except Exception as exc:
                return outcome(
                    "ERROR",
                    message=f"не удалось открыть hh.ru для проверки сессии: {exc}",
                )
            page.wait_for_timeout(800)
            if _is_login_url(page.url) or not _logged_in(page):
                return outcome(
                    "NEEDS_LOGIN",
                    reason="login_required",
                    message="сохранённая сессия недействительна: выполните login заново",
                )
            account = ""
            element = page.query_selector("[data-qa='mainmenu_profileAndResumes']")
            if element is not None:
                account = account_label(element.inner_text() or "")
            message = "сессия активна" + (f": {account}" if account else "")
            return outcome("OK", message=message)
        finally:
            browser.close()


def run_import(from_path: str, config: dict, repo: Path) -> dict:
    """Copy an existing Playwright ``storage_state.json`` into the repo.

    Only the structure is validated; cookie values are never printed.
    """
    storage = _storage_state_path(config, repo)
    source = Path(from_path).expanduser()
    if not source.is_absolute():
        source = Path(repo) / source
    if not source.is_file():
        raise DriverError(f"файл не найден: {from_path}")
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise DriverError(f"не удалось прочитать storage_state: {exc}") from None
    if not isinstance(payload, dict) or not (
        isinstance(payload.get("cookies"), list)
        or isinstance(payload.get("origins"), list)
    ):
        raise DriverError(
            "это не Playwright storage_state.json (ожидаются ключи cookies/origins)"
        )
    storage.parent.mkdir(parents=True, exist_ok=True)
    storage.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return outcome("OK", message=f"сессия импортирована: {storage}")


def run(mode: str, ref: str, config: dict, repo: Path, letter: str | None = None) -> dict:
    repo = Path(repo)
    if mode == "login":
        return run_login(config, repo)
    if mode == "verify":
        return run_verify(config, repo)
    if mode == "check":
        return run_check(ref, config, repo)
    if mode == "apply":
        return run_apply(ref, config, repo, letter)
    if mode == "attach":
        if not letter:
            raise DriverError("attach требует --letter <path>")
        return run_attach(ref, config, repo, letter)
    if mode == "status":
        return run_status(ref, config, repo)
    raise DriverError(f"неизвестный режим: {mode}")


def render_text(result: dict) -> str:
    """Human-readable rendering for the default (non-JSON) output."""
    lines = [f"STATUS: {result['status']}"]
    if result.get("reason"):
        lines.append(f"REASON: {result['reason']}")
    if result.get("url"):
        lines.append(f"URL: {result['url']}")
    if result.get("resume"):
        resume = result["resume"]
        lines.append(f"RESUME: {resume.get('title') or resume.get('id') or ''}")
    if result.get("cover_letter_used"):
        lines.append(f"COVER_LETTER: {result['cover_letter_used']}")
    if result.get("response_id"):
        lines.append(f"RESPONSE_ID: {result['response_id']}")
    if result.get("missing_fields"):
        lines.append("MISSING_FIELDS: " + ", ".join(result["missing_fields"]))
    if result.get("debug"):
        lines.append(f"DEBUG: {result['debug']}")
    if result.get("message"):
        lines.append(f"MESSAGE: {result['message']}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)  # absent on a StringIO under test
        if reconfigure:
            reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Drive the hh.ru response form")
    parser.add_argument(
        "mode", choices=("login", "verify", "check", "apply", "attach", "status")
    )
    parser.add_argument("--url", default="", help="hh.ru vacancy URL or id")
    parser.add_argument("--letter", default="", help="plain-text cover letter path")
    parser.add_argument(
        "--from",
        default="",
        dest="from_path",
        help="import an existing Playwright storage_state.json (login only)",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--repo", type=Path, default=ROOT)
    args = parser.parse_args(argv)

    config = resolve_config(repo=args.repo)
    try:
        if args.mode == "login" and args.from_path:
            result = run_import(args.from_path, config, args.repo)
        else:
            result = run(args.mode, args.url, config, args.repo, args.letter or None)
    except DriverError as exc:
        result = outcome("ERROR", message=str(exc))
    except Exception as exc:  # pragma: no cover - defensive top-level guard
        result = outcome("ERROR", message=f"unexpected {type(exc).__name__}: {exc}")

    if args.as_json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(render_text(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
