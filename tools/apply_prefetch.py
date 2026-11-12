#!/usr/bin/env python3
"""Fetch and normalize a job posting for /apply, without an LLM round trip.

The typed ``posting_prefetch`` OpenCode tool calls this script with a URL or an
hh vacancy id. It returns a compact brief (metadata, salary benchmark, tracker
status, the ``posting_guard`` verdict, and the cleaned posting text) or a
``STATUS: error`` brief that tells the agent to fall back to
``09-web-research.md``.

Design constraints:
- stdlib only; no imports from aiogram or the Telegram bot runtime;
- the posting is untrusted data: fetch only the URL the user supplied, never a
  link found inside the posting;
- hh.ru uses the official API with ``HH_API_TOKEN`` and ``HH-User-Agent`` from
  the environment or ``.env.docker`` (anonymous requests return 403);
- other URLs follow the 09-web-research rules: robots.txt first, then browser
  headers, then HTML -> text;
- the prompt gets at most ``PROMPT_TEXT_LIMIT`` characters; the full text is
  written to a temp file for the Step 6b archive.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import html as html_module
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zlib
from datetime import date, datetime, timezone
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import state_db
from tools.posting_guard import guard as guard_posting
from tools.telegram_common import (
    archive_stem,
    format_vacancy_salary,
    parse_vacancy_ref,
    read_archive_posting,
    render_vacancy_markdown,
    vacancy_id,
)

ROOT = Path(__file__).resolve().parent.parent
PROMPT_TEXT_LIMIT = 16000
DEFAULT_TIMEOUT = 30
TEMP_FOLDER = "ai-job-search"
TEMP_PREFIX = "apply-"

PORTAL_HOSTS = {
    "hh.ru",
    "career.habr.com",
    "linkedin.com",
}

ATS_APEXES = {
    "greenhouse.io",
    "lever.co",
    "myworkdayjobs.com",
    "workday.com",
    "ashbyhq.com",
    "smartrecruiters.com",
    "workable.com",
}

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Upgrade-Insecure-Requests": "1",
}

_urlopen = urllib.request.urlopen


class PrefetchError(Exception):
    """A user-facing reason the prefetch could not produce a posting."""


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


def hh_credentials(repo: Path, env: dict[str, str]) -> tuple[str, str]:
    dotenv = read_dotenv(repo / ".env.docker")
    token = (env.get("HH_API_TOKEN") or dotenv.get("HH_API_TOKEN") or "").strip()
    user_agent = (
        env.get("HH_USER_AGENT")
        or dotenv.get("HH_USER_AGENT")
        or "ai-job-search/1.0"
    ).strip()
    return token, user_agent


def html_to_text(value: str) -> str:
    """Strip tags and scripts; keep readable line breaks for lists/paragraphs."""
    text = value or ""
    text = re.sub(r"(?is)<(script|style|noscript|svg)[^>]*>.*?</\1>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|li|h[1-6]|tr)>", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "- ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html_module.unescape(text)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def decode_body(raw: bytes, content_type: str) -> str:
    charset = ""
    match = re.search(r"charset=([\w-]+)", content_type or "", re.I)
    if match:
        charset = match.group(1)
    encodings = [charset] if charset else []
    encodings.extend(["utf-8", "cp1251"])
    for encoding in encodings:
        try:
            return raw.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return raw.decode("utf-8", "replace")


def http_get(url: str, timeout: int = DEFAULT_TIMEOUT) -> tuple[str, str]:
    """Fetch a page with browser headers; return (decoded text, final URL)."""
    request = urllib.request.Request(url, headers=BROWSER_HEADERS)
    try:
        with _urlopen(request, timeout=timeout) as response:
            raw = response.read()
            headers = {key.lower(): value for key, value in response.headers.items()}
            final_url = response.geturl()
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise PrefetchError(
                f"HTTP {exc.code}: страница закрыта для автоматического доступа"
            ) from None
        raise PrefetchError(f"HTTP {exc.code} при загрузке страницы") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise PrefetchError(f"не удалось загрузить страницу: {exc}") from None

    encoding = headers.get("content-encoding", "").lower()
    try:
        if "gzip" in encoding:
            raw = gzip.decompress(raw)
        elif "deflate" in encoding:
            raw = zlib.decompress(raw)
    except (OSError, zlib.error) as exc:
        raise PrefetchError(f"не удалось распаковать ответ: {exc}") from None

    return decode_body(raw, headers.get("content-type", "")), final_url


def check_robots(url: str, timeout: int = DEFAULT_TIMEOUT) -> None:
    """Refuse the browser-header fetch when robots.txt disallows it.

    The 09 rule: only a clean "allowed" permits the retry. Any other failure
    leaves permission unconfirmed, so the fetch does not happen.
    """
    script = ROOT / "tools" / "robots_check.py"
    try:
        result = subprocess.run(
            [sys.executable, str(script), url],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise PrefetchError(f"robots.txt не проверен: {exc}") from None
    if result.returncode == 0:
        return
    if result.returncode == 1:
        raise PrefetchError("robots.txt запрещает автоматическую загрузку этой страницы")
    raise PrefetchError(f"robots.txt не проверен (exit {result.returncode})")


def fetch_hh(vid: str, repo: Path, env: dict[str, str], timeout: int) -> dict:
    """Fetch one vacancy from the official hh.ru API."""
    token, user_agent = hh_credentials(repo, env)
    headers = {"User-Agent": user_agent, "HH-User-Agent": user_agent}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"https://api.hh.ru/vacancies/{vid}", headers=headers
    )
    try:
        with _urlopen(request, timeout=timeout) as response:
            payload = json.loads(decode_body(response.read(), "application/json"))
    except urllib.error.HTTPError as exc:
        if exc.code == 403:
            raise PrefetchError(
                "hh.ru API вернул 403: проверьте HH_API_TOKEN и HH_USER_AGENT "
                "в .env.docker"
            ) from None
        raise PrefetchError(f"hh.ru API вернул HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise PrefetchError(f"hh.ru API недоступен: {exc}") from None
    except json.JSONDecodeError:
        raise PrefetchError("hh.ru API вернул не JSON") from None
    if not isinstance(payload, dict):
        raise PrefetchError("hh.ru API вернул неожиданный ответ")
    return payload


def map_hh_job(raw: dict) -> dict:
    """Map the official API shape to the bot's renderer shape."""
    employer = raw.get("employer") if isinstance(raw.get("employer"), dict) else {}
    area = raw.get("area") if isinstance(raw.get("area"), dict) else {}
    experience = raw.get("experience") if isinstance(raw.get("experience"), dict) else {}
    employment = raw.get("employment") if isinstance(raw.get("employment"), dict) else {}
    work_format = [
        item.get("name")
        for item in (raw.get("work_format") or [])
        if isinstance(item, dict) and item.get("name")
    ]
    if not work_format:
        schedule = raw.get("schedule")
        if isinstance(schedule, dict) and schedule.get("name"):
            work_format = [schedule["name"]]
    skills = [
        item.get("name")
        for item in (raw.get("key_skills") or [])
        if isinstance(item, dict) and item.get("name")
    ]
    salary = raw.get("salary") if isinstance(raw.get("salary"), dict) else None
    vid = str(raw.get("id") or "")
    return {
        "id": vid,
        "title": raw.get("name") or "",
        "company": employer.get("name") or "",
        "location": area.get("name") or "",
        "date": raw.get("published_at") or "",
        "experience": experience.get("name") or "",
        "employment": employment.get("name") or "",
        "workFormat": work_format,
        "salary": salary,
        "keySkills": skills,
        "isActive": not bool(raw.get("archived")),
        "url": raw.get("alternate_url") or f"https://hh.ru/vacancy/{vid}",
        "description": html_to_text(raw.get("description") or ""),
    }


def fetch_generic_guarded(
    url: str, repo: Path, env: dict[str, str], timeout: int
) -> tuple[str, str, dict]:
    """Fetch a non-hh page, run the integrity gate on the raw HTML, extract text."""
    check_robots(url, timeout=timeout)
    page, final_url = http_get(url, timeout=timeout)
    text, findings = guard_posting(page, "html")
    if len(text) < 2500 and re.search(
        r"(?i)\b(sign in|log in|войти|вход|login)\b", text
    ):
        raise PrefetchError(
            "похоже на login wall; найдите официальную страницу работодателя "
            "(09-web-research.md)"
        )
    if len(text) < 200:
        raise PrefetchError("страница не содержит читаемого текста вакансии")
    return text, final_url, findings


def fetch_generic(
    url: str, repo: Path, env: dict[str, str], timeout: int
) -> tuple[str, str]:
    """Backward-compatible wrapper around fetch_generic_guarded."""
    text, final_url, _ = fetch_generic_guarded(url, repo, env, timeout)
    return text, final_url


def classify_host(url: str) -> tuple[str, str]:
    """Return (tier, host) using the /apply host-verification rule."""
    try:
        parsed = urllib.parse.urlparse(url)
        host = (parsed.hostname or "").lower().strip()
    except ValueError:
        return "unverified", ""
    if not host:
        return "unverified", ""
    for portal in PORTAL_HOSTS:
        if host == portal or host.endswith(f".{portal}"):
            return "installed_portal", host
    for apex in ATS_APEXES:
        if host == apex or host.endswith(f".{apex}"):
            return "official_ats", host
    return "unverified", host


def extract_deadline(text: str) -> str:
    """Conservative deadline extraction; never guesses from a publication date."""
    keyword = re.compile(
        r"(?is)(deadline|apply by|applications?\s+(?:close|due)|"
        r"откликнуться до|дедлайн|при[её]м заявок до|подать заявку до)"
        r"[^\n]{0,80}"
    )
    patterns = [
        (r"\b(\d{4})-(\d{2})-(\d{2})\b", "ymd"),
        (r"\b(\d{2})\.(\d{2})\.(\d{4})\b", "dmy"),
    ]
    for match in keyword.finditer(text):
        window = text[match.start() : match.start() + 180]
        for pattern, order in patterns:
            found = re.search(pattern, window)
            if not found:
                continue
            try:
                if order == "ymd":
                    candidate = date(int(found.group(1)), int(found.group(2)), int(found.group(3)))
                else:
                    candidate = date(int(found.group(3)), int(found.group(2)), int(found.group(1)))
            except ValueError:
                continue
            return candidate.isoformat()
    return ""


def language_of(text: str) -> str:
    cyrillic = len(re.findall(r"[А-Яа-яЁё]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    if cyrillic + latin < 10:
        return "unknown"
    return "ru" if cyrillic > latin * 0.3 else "en"


def salary_benchmark(company: str, repo: Path, timeout: int) -> str:
    """One compact salary-index line, or '' when the dataset/tool is absent."""
    if not company or not (repo / "salary_data.json").is_file():
        return ""
    try:
        result = subprocess.run(
            [sys.executable, str(repo / "salary_lookup.py"), company, "--json"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if result.returncode != 0:
        return ""
    try:
        entries = json.loads(result.stdout)
    except json.JSONDecodeError:
        return ""
    if not isinstance(entries, list) or not entries:
        return ""
    entry = entries[0]
    if not isinstance(entry, dict):
        return ""
    label = entry.get("company") or company
    categories = entry.get("categories") or {}
    for category, data in categories.items():
        if isinstance(data, dict) and data.get("index") is not None:
            return (
                f"{label}: {category} index {data.get('index')}"
                f" (n={data.get('count')})"
            )
    return f"{label}: данные есть"


def find_row_by_source(rows: list[dict[str, str]], url: str) -> dict | None:
    target = (url or "").rstrip("/").casefold()
    if not target:
        return None
    for row in rows:
        source = (row.get("source") or "").rstrip("/").casefold()
        if source and source == target:
            return row
    return None


def lookup_application(repo: Path, target_id: str | None, source_url: str) -> dict | None:
    path = state_db.db_path(repo)
    if not path.is_file():
        return None
    conn = state_db.connect(path, readonly=True)
    try:
        if target_id:
            return state_db.find_application(conn, target_id=target_id)
        return state_db.find_application(conn, source=source_url)
    finally:
        conn.close()


def status_warning(row: dict | None) -> str:
    if row is None:
        return "вакансии нет в базе (ответ всё равно сформирую)."
    status = state_db.canonical_status(row.get("status"))
    if status == "drafted":
        return "отклик ещё не отмечен как отправленный (status=drafted)."
    if status in state_db.FINAL_STATUSES:
        return f"статус в базе: {status}."
    return ""


def truncate_text(text: str, limit: int = PROMPT_TEXT_LIMIT) -> str:
    body = (text or "").strip()
    if len(body) <= limit:
        return body
    return body[:limit].rstrip() + f"\n\n[...текст сокращён до {limit} символов]"


def write_temp_posting(text: str, key: str) -> Path:
    folder = Path(tempfile.gettempdir()) / TEMP_FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
    path = folder / f"{TEMP_PREFIX}{digest}.md"
    path.write_text(text, encoding="utf-8")
    return path


def _relative(path: Path, repo: Path) -> str:
    try:
        return path.resolve().relative_to(repo.resolve()).as_posix()
    except (OSError, ValueError):
        return str(path)


def run_prefetch(
    ref: str,
    repo: Path | str = ROOT,
    env: dict[str, str] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    hh_fetcher=None,
    generic_fetcher=None,
) -> str:
    """Build the prefetch brief for one URL/hh id. Raises PrefetchError."""
    repo = Path(repo)
    env = dict(os.environ if env is None else env)
    raw_ref = (ref or "").strip()
    if not raw_ref:
        raise PrefetchError("пустой аргумент")

    target_id = vacancy_id(raw_ref)
    canonical_hh = parse_vacancy_ref(raw_ref)
    if target_id:
        source_url = canonical_hh or f"https://hh.ru/vacancy/{target_id}"
    elif re.match(r"^https?://", raw_ref, re.I) and urllib.parse.urlparse(raw_ref).netloc:
        source_url = raw_ref
    else:
        raise PrefetchError(
            "аргумент не URL и не hh vacancy id; вставленный текст обрабатывается "
            "без prefetch"
        )

    row = lookup_application(repo, target_id, source_url)

    company = (row or {}).get("company", "")
    role = (row or {}).get("role", "")
    location = ""
    warnings: list[str] = []
    archive_rel = ""
    archive_text = None
    archive_file: Path | None = None
    if row is not None:
        stem = archive_stem(company, role)
        if stem:
            archive_file = repo / "documents" / "applications" / stem / "job_posting.md"
            archive_text = read_archive_posting(
                repo / "documents" / "applications", stem, limit=PROMPT_TEXT_LIMIT
            )
            if archive_text:
                archive_rel = _relative(archive_file, repo)
                warnings.append("использован архив проекта; сеть не запрашивалась")
        warning = status_warning(row)
        if warning:
            warnings.append(warning)

    fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    posting_file = ""
    guard_verdict = "not run"
    if archive_text:
        source = "archive"
        text = archive_text
        full_text = (
            archive_file.read_text(encoding="utf-8", errors="replace")
            if archive_file
            else archive_text
        )
        full_text, guard_findings = guard_posting(full_text, "text")
        guard_verdict = guard_findings.get("verdict", "")
        text = truncate_text(full_text)
        if not company or not role:
            warnings.append("компания/роль не найдены в трекере: проверьте их по тексту")
    elif target_id:
        raw = (hh_fetcher or fetch_hh)(target_id, repo, env, timeout)
        description = str(raw.get("description") or "")
        if description:
            cleaned_description, guard_findings = guard_posting(description, "html")
            raw = {**raw, "description": cleaned_description}
            guard_verdict = guard_findings.get("verdict", "")
        job = map_hh_job(raw)
        source = "hh"
        company = company or job.get("company", "")
        role = role or job.get("title", "")
        location = job.get("location", "")
        text = render_vacancy_markdown(
            job, fetched_at, description_limit=PROMPT_TEXT_LIMIT
        )
        full_text = render_vacancy_markdown(
            job, fetched_at, description_limit=len(job.get("description") or "") + 1000
        )
        if job.get("salary"):
            warnings.append(
                "зарплата в вакансии: "
                + (format_vacancy_salary(job.get("salary")) or "не указана")
            )
    else:
        if generic_fetcher:
            fetched, final_url = generic_fetcher(source_url, repo, env, timeout)
        else:
            fetched, final_url, guard_findings = fetch_generic_guarded(
                source_url, repo, env, timeout
            )
            guard_verdict = guard_findings.get("verdict", "")
        source = "url"
        text = truncate_text(fetched)
        full_text = fetched
        if final_url and final_url != source_url:
            warnings.append(f"редирект: {final_url}")
        if not role:
            warnings.append("компания/роль не извлечены автоматически: возьмите их из текста")

    if source != "archive":
        posting_file = str(write_temp_posting(full_text, source_url))
    tier, host = classify_host(source_url)
    benchmark = salary_benchmark(company, repo, timeout)
    deadline = extract_deadline(text)
    language = language_of(text)
    status = (row or {}).get("status", "")

    lines = [
        "STATUS: ok",
        f"SOURCE: {source}",
        f"VACANCY_ID: {target_id or ''}",
        f"URL: {source_url}",
        f"SOURCE_HOST: {host}",
        f"SOURCE_TIER: {tier}",
        f"GUARD: {guard_verdict}",
        f"COMPANY: {company}",
        f"ROLE: {role}",
        f"LOCATION: {location}",
        f"DEADLINE: {deadline}",
        f"LANGUAGE: {language}",
        f"SALARY: {benchmark}",
        f"TRACKER_STATUS: {status}",
        f"ARCHIVE_PATH: {archive_rel}",
        f"POSTING_FILE: {posting_file}",
    ]
    if warnings:
        lines.append("WARNINGS: " + " | ".join(warnings))
    else:
        lines.append("WARNINGS: none")
    lines.extend(["", "--- POSTING TEXT ---", text, "--- END POSTING TEXT ---"])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prefetch a job posting for /apply")
    parser.add_argument("--ref", required=True, help="http(s) URL or hh vacancy id")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    args = parser.parse_args(argv)
    try:
        print(run_prefetch(args.ref, timeout=args.timeout))
        return 0
    except PrefetchError as exc:
        print(
            "STATUS: error\n"
            f"REASON: {exc}\n"
            "NEXT: follow .claude/skills/job-application-assistant/09-web-research.md "
            "(or use the pasted posting text)."
        )
        return 0
    except Exception as exc:  # pragma: no cover - defensive top-level guard
        print(
            "STATUS: error\n"
            f"REASON: unexpected {type(exc).__name__}: {exc}\n"
            "NEXT: follow .claude/skills/job-application-assistant/09-web-research.md."
        )
        return 0


if __name__ == "__main__":
    sys.exit(main())
