"""Shared constants, errors, paths, and normalizers."""

from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from tools.job_key import make_key

ROOT = Path(__file__).resolve().parents[2]
STATE_DIR = ROOT / "state"
DB_PATH = STATE_DIR / "job_search.sqlite"
MIGRATIONS = STATE_DIR / "migrations"
BACKUPS = ROOT / "backups"
APPLICATIONS_DIR = ROOT / "documents" / "applications"
CV_MASTER = ROOT / "cv" / "main_example.tex"

WEIGHTS = {"technical": 0.30, "experience": 0.25, "behavioral": 0.15, "career": 0.30}
BANDS = ((75, "Strong Fit"), (60, "Good Fit"), (45, "Moderate Fit"), (30, "Weak Fit"), (0, "Poor Fit"))
URGENT_DAYS = 7

FINAL_STATUSES = {"hired", "rejected", "no_response", "offer_declined", "withdrawn", "interview_only"}
STATUS_ALIASES = {
    "no response": "no_response",
    "offer declined": "offer_declined",
}
COVER_LETTER_VALUES = {"used", "not_used", "not_required", "unknown"}
STAGES = ("phone_screen", "technical", "technical_2", "case", "final", "offer")
STAGE_ALIASES = {
    "phone screen": "phone_screen",
    "phone_screen": "phone_screen",
    "technical interview": "technical",
    "technical": "technical",
    "technical interview 2": "technical_2",
    "technical interview #2": "technical_2",
    "technical round 2": "technical_2",
    "technical 2": "technical_2",
    "technical_2": "technical_2",
    "second technical": "technical_2",
    "case interview": "case",
    "case": "case",
    "final round": "final",
    "final": "final",
    "offer received": "offer",
    "offer": "offer",
}
STAGE_LABELS = {
    "phone_screen": "Phone screen",
    "technical": "Technical interview",
    "technical_2": "Technical interview #2",
    "case": "Case interview",
    "final": "Final round",
    "offer": "Offer received",
}

EVENT_TYPES = {
    "drafted", "submitted", "response_received", "interview_status",
    "interview_scheduled", "interview_completed", "stage_reached",
    "offer_received", "offer_accepted", "offer_declined", "hired",
    "rejected", "no_response", "withdrawn", "interview_only",
    "follow_up_sent", "status_changed", "note",
}
STATUS_EVENT_TYPES = {
    "drafted": "drafted",
    "applied": "submitted",
    "interview": "interview_status",
    "offer": "offer_received",
    "hired": "hired",
    "rejected": "rejected",
    "no_response": "no_response",
    "offer_declined": "offer_declined",
    "withdrawn": "withdrawn",
    "interview_only": "interview_only",
    "unknown": "status_changed",
}


class StateError(Exception):
    """A user-facing state or database error."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _today() -> str:
    return date.today().isoformat()


def norm(text: object) -> str:
    value = unicodedata.normalize("NFC", str(text or "").casefold())
    return "".join(ch for ch in value if ch.isalnum() or unicodedata.category(ch).startswith("M"))


def detect_language(text: object) -> str:
    value = str(text or "")
    cyrillic = len(re.findall(r"[А-Яа-яЁё]", value))
    latin = len(re.findall(r"[A-Za-z]", value))
    if cyrillic + latin < 10:
        return "unknown"
    return "ru" if cyrillic > latin * 0.3 else "en"


def status_norm(value: object) -> str:
    text = " ".join(str(value or "").strip().casefold().replace("-", " ").split())
    text = text.replace(" ", "_") if text in {"no_response", "offer_declined"} else text
    return STATUS_ALIASES.get(text, text)


def canonical_status(value: object, default: str = "unknown") -> str:
    text = status_norm(value)
    aliases = {
        "no_response": "no_response",
        "offer_declined": "offer_declined",
        "drafted": "drafted",
        "applied": "applied",
        "interview": "interview",
        "offer": "offer",
        "hired": "hired",
        "rejected": "rejected",
        "withdrawn": "withdrawn",
        "interview_only": "interview_only",
    }
    return aliases.get(text, default)


def canonical_cover_letter(value: object) -> str:
    text = " ".join(str(value or "").strip().casefold().replace("-", " ").split())
    mapping = {
        "used": "used",
        "sent": "used",
        "yes": "used",
        "not used": "not_used",
        "not_used": "not_used",
        "no": "not_used",
        "not required": "not_required",
        "not_required": "not_required",
        "unknown": "unknown",
    }
    return mapping.get(text, "unknown")


def parse_date(value: object) -> str | None:
    text = str(value or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return None
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def archive_stem(company: object, role: object) -> str:
    raw = f"{company or ''}_{role or ''}".lower().replace(" ", "_")
    kept = "".join(ch for ch in raw if ch.isalnum() or ch == "_")
    return re.sub(r"_+", "_", kept).strip("_")


def url_norm(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = urlparse(text)
    if not parsed.netloc:
        return text.casefold()
    query = [
        (key, val)
        for key, val in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_")
        and key.casefold() not in {"tech_source", "from", "hhtmfrom", "source"}
    ]
    path = parsed.path.rstrip("/")
    return urlunparse(
        (parsed.scheme.casefold(), parsed.netloc.casefold(), path, "", urlencode(query), "")
    )

def _row_value(row: sqlite3.Row | dict, key: str, default: str = "") -> str:
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        return default
    return str(value or "")


def _load_json(value: object, default):
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(str(value or ""))
    except (TypeError, ValueError):
        return default

def _normalize_archive_dir(value: object) -> str:
    path = Path(str(value or ""))
    if path.suffix.casefold() == ".md":
        return path.parent.as_posix()
    return path.as_posix()

__all__ = [name for name in globals() if not name.startswith("__")]

POSTING_URL_RE = re.compile(r"https?://[^\s)>\]\"']+")


def _posting_urls(text: str) -> set[str]:
    return {url_norm(match.group(0)) for match in POSTING_URL_RE.finditer(text or "") if match.group(0)}


def _posting_vacancy_ids(text: str) -> set[str]:
    return {
        match.group(1)
        for match in re.finditer(r"(?:hh\.ru|api\.hh\.ru)/(?:vacancy|vacancies)/(\d+)", text or "")
    }


def _folder_vacancy_id(path: object) -> str:
    match = re.search(r"_(\d{6,})$", Path(str(path or "")).name)
    return match.group(1) if match else ""


def _app_vacancy_id(app: dict) -> str:
    return hh_vacancy_id(app.get("source_url")) or _folder_vacancy_id(app.get("archive_path"))


def hh_vacancy_id(value: object) -> str:
    match = re.search(r"(?:hh\.ru|api\.hh\.ru)/(?:vacancy|vacancies)/(\d+)", str(value or ""), re.IGNORECASE)
    return match.group(1) if match else ""


__all__ = [name for name in globals() if not name.startswith("__")]
