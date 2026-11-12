"""Archived-posting and job-description migration."""

from __future__ import annotations

import hashlib
import re

from .common import *
from .jobs import *
from .applications import *

POSTING_URL_RE = re.compile(r"https?://[^\s)>\]\"']+")

def _posting_matches_app(text: str, app: dict) -> bool:
    expected_id = _app_vacancy_id(app)
    if expected_id:
        return expected_id in _posting_vacancy_ids(text)
    expected_url = url_norm(app.get("source_url"))
    if expected_url:
        return expected_url in _posting_urls(text)
    return True

def _repair_archive_paths(
    conn: sqlite3.Connection, base: Path, *, write: bool
) -> list[dict]:
    apps = [dict(row) for row in conn.execute("SELECT * FROM applications ORDER BY id")]
    repairs = []
    for app in apps:
        old = str(app.get("archive_path") or "")
        if not old:
            continue
        new_dir = _normalize_archive_dir(old)
        if new_dir == old:
            continue
        repairs.append(
            {
                "application_id": app.get("id"),
                "company": app.get("company"),
                "role": app.get("role"),
                "old": old,
                "new": new_dir,
                "reason": "file_to_directory",
            }
        )
        if write:
            outcome_path = f"{new_dir}/outcome.md"
            conn.execute(
                "UPDATE applications SET archive_path=?, outcome_note_path=?, updated_at=? WHERE id=?",
                (new_dir, outcome_path if (base / outcome_path).is_file() else "", _now(), app.get("id")),
            )
    if write:
        conn.commit()
    return repairs


def _find_posting_for_app(
    base: Path, app: dict
) -> tuple[Path | None, str]:
    apps_dir = base / "documents" / "applications"
    own = base / _normalize_archive_dir(app.get("archive_path"))
    expected = _app_vacancy_id(app) or url_norm(app.get("source_url"))
    own_candidates = sorted(own.glob("job_posting*.md")) if own.is_dir() else []
    fallback: tuple[Path | None, str] = (None, "")
    for posting in own_candidates:
        try:
            text = posting.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if not fallback[0]:
            fallback = (posting, text)
        if expected and (expected in _posting_vacancy_ids(text) or expected in _posting_urls(text)):
            return posting, text
        if not expected and _posting_matches_app(text, app):
            return posting, text
    if not expected or not apps_dir.is_dir():
        return fallback
    matches = []
    for posting in sorted(apps_dir.glob("*/job_posting*.md")):
        try:
            text = posting.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if expected in _posting_vacancy_ids(text) or expected in _posting_urls(text):
            matches.append((posting, text))
    if len(matches) == 1:
        return matches[0]
    return None, ""


def _job_identity_matches_app(job: dict, app: dict) -> bool:
    expected_id = _app_vacancy_id(app)
    job_id = hh_vacancy_id(job.get("url"))
    if expected_id:
        return not job_id or job_id == expected_id
    expected_url = url_norm(app.get("source_url"))
    job_url = url_norm(job.get("url"))
    if expected_url:
        return not job_url or job_url == expected_url
    return True

def _job_match_for_app(
    conn: sqlite3.Connection, app: dict, posting_text: str
) -> tuple[dict | None, str]:
    mismatch = False
    job_key = str(app.get("job_key") or "").strip()
    if job_key:
        row = _job_row(conn, job_key)
        if row:
            if _job_identity_matches_app(row, app):
                return row, "job_key"
            mismatch = True
    source = str(app.get("source_url") or "").strip()
    if source:
        row = conn.execute(
            "SELECT * FROM jobs WHERE url_norm=? ORDER BY first_seen DESC LIMIT 1",
            (url_norm(source),),
        ).fetchone()
        if row:
            return dict(row), "url"
    for url in _posting_urls(posting_text):
        row = conn.execute(
            "SELECT * FROM jobs WHERE url_norm=? ORDER BY first_seen DESC LIMIT 1",
            (url,),
        ).fetchone()
        if row:
            return dict(row), "posting_url"
    company_norm = str(app.get("company_norm") or norm(app.get("company")))
    role_norm = str(app.get("role_norm") or norm(app.get("role")))
    if company_norm and role_norm:
        rows = [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM jobs WHERE company_norm=? ORDER BY first_seen DESC",
                (company_norm,),
            )
        ]
        matches = [
            row
            for row in rows
            if norm(row.get("title")) == role_norm and _job_identity_matches_app(row, app)
        ]
        if len(matches) == 1:
            return matches[0], "company_title"
        if len(matches) > 1:
            return None, "ambiguous"
    return None, "job_key_mismatch" if mismatch else "unmatched"


def _archived_job_key(
    conn: sqlite3.Connection, app: dict, url: str, reserved: set[str] | None = None
) -> str:
    company = str(app.get("company") or "")
    role = str(app.get("role") or "")
    base_key = make_key(company, role, url)
    reserved = reserved or set()
    row = _job_row(conn, base_key)
    if row is None and base_key not in reserved:
        return base_key
    if row is not None and url_norm(url) and url_norm(row.get("url")) == url_norm(url):
        return base_key
    if row is not None and not url and norm(row.get("company")) == norm(company) and norm(row.get("title")) == norm(role):
        return base_key
    suffix = hh_vacancy_id(url) or hashlib.sha1(
        (url or str(app.get("archive_path") or "")).encode("utf-8")
    ).hexdigest()[:6]
    candidate = f"{base_key}-{suffix}"
    while _job_row(conn, candidate) is not None or candidate in reserved:
        suffix = hashlib.sha1(candidate.encode("utf-8")).hexdigest()[:6]
        candidate = f"{base_key}-{suffix}"
    return candidate


def backfill_archived_jobs(
    conn: sqlite3.Connection,
    repo: Path | str | None = None,
    *,
    write: bool = False,
    replace_description: bool = False,
) -> dict:
    """Link every application to a job, creating historical archived jobs."""
    base = Path(repo) if repo else ROOT
    repairs = _repair_archive_paths(conn, base, write=write)
    report = {
        "mode": "write" if write else "dry-run",
        "applications": 0,
        "reused": 0,
        "created": 0,
        "linked": 0,
        "descriptions": 0,
        "missing_posting": 0,
        "ambiguous": 0,
        "archive_repairs": repairs,
        "details": [],
    }
    apps = [dict(row) for row in conn.execute("SELECT * FROM applications ORDER BY id")]
    planned_urls: dict[str, str] = {}
    planned_keys: set[str] = set()
    for app in apps:
        report["applications"] += 1
        detail = {
            "application_id": app.get("id"),
            "company": app.get("company"),
            "role": app.get("role"),
            "action": "",
            "job_key": app.get("job_key") or "",
            "posting": "",
        }
        posting_path, posting_text = _find_posting_for_app(base, app)
        detail["posting"] = posting_path.as_posix() if posting_path else ""
        if not posting_text:
            report["missing_posting"] += 1
        job, method = _job_match_for_app(conn, app, posting_text)
        if job is None and not write:
            candidate_urls = [url_norm(app.get("source_url"))] + sorted(_posting_urls(posting_text))
            planned = next((planned_urls[url] for url in candidate_urls if url in planned_urls), "")
            if planned:
                job = {"job_key": planned, "description_text": ""}
                method = "planned_url"
        detail["match"] = method
        if job is None and method == "ambiguous":
            report["ambiguous"] += 1
            detail["action"] = "ambiguous"
            report["details"].append(detail)
            continue
        if job is None:
            url = str(app.get("source_url") or "").strip()
            if not url and posting_text:
                urls = sorted(_posting_urls(posting_text))
                url = next((item for item in urls if "hh.ru/vacancy/" in item), "")
            key = _archived_job_key(conn, app, url, planned_keys)
            planned_keys.add(key)
            if url:
                planned_urls.setdefault(url_norm(url), key)
            payload = {
                "title": str(app.get("role") or ""),
                "company": str(app.get("company") or ""),
                "url": url,
                "portal": "archive",
                "source": "archive",
                "status": "archived",
                "first_seen": parse_date(app.get("applied_on")),
                "deadline": parse_date(app.get("deadline")),
                "description_text": posting_text,
                "language": detect_language(posting_text),
                "archive_path": _normalize_archive_dir(app.get("archive_path")),
                "application_id": app.get("id"),
            }
            if write:
                job = upsert_job(conn, payload, key=key)
                conn.execute(
                    "UPDATE applications SET job_key=?, updated_at=? WHERE id=?",
                    (key, _now(), app.get("id")),
                )
            else:
                job = dict(payload, job_key=key)
            report["created"] += 1
            report["linked"] += 1
            if posting_text:
                report["descriptions"] += 1
            detail["action"] = "created"
            detail["job_key"] = key
        else:
            report["reused"] += 1
            detail["old_job_key"] = app.get("job_key") or ""
            detail["job_key"] = job.get("job_key")
            if app.get("job_key") != job.get("job_key"):
                report["linked"] += 1
                detail["action"] = (
                    "relinked" if app.get("job_key") else "linked"
                )
                if write:
                    conn.execute(
                        "UPDATE applications SET job_key=?, updated_at=? WHERE id=?",
                        (job["job_key"], _now(), app.get("id")),
                    )
            else:
                detail["action"] = "reused"
        if posting_text and posting_path and job is not None:
            if job.get("description_text") and not replace_description:
                pass
            elif write:
                if _set_job_description(
                    conn, _job_row(conn, job["job_key"]) or job, posting_text, posting_path,
                    replace=replace_description,
                ):
                    report["descriptions"] += 1
            elif not job.get("description_text") or replace_description:
                report["descriptions"] += 1
        report["details"].append(detail)
    if write:
        conn.commit()
    return report

__all__ = [name for name in globals() if not name.startswith("__")]
