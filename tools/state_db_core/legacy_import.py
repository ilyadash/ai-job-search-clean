"""One-time legacy tracker/seen-jobs importer."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from .common import *
from .db import *
from .jobs import *
from .applications import *

def seed_legacy(conn: sqlite3.Connection, seen: dict, tracker_path: Path | None = None) -> None:
    for key, entry in seen.items():
        if isinstance(entry, dict):
            upsert_job(conn, entry, key=str(key))
    if tracker_path:
        _, rows = _read_tracker(tracker_path)
        for row in rows:
            company = str(row.get("company") or "").strip()
            role = str(row.get("role") or "").strip()
            if not company and not role:
                continue
            status_value = canonical_status(row.get("status"))
            row_date = parse_date(row.get("date"))
            timestamps = (
                {"created_at": f"{row_date}T00:00:00+00:00", "updated_at": f"{row_date}T00:00:00+00:00"}
                if row_date
                else {}
            )
            _insert_application(
                conn,
                {
                    "applied_on": row_date if status_value not in {"drafted", "unknown"} else None,
                    "status": status_value,
                    "company": company,
                    "role": role,
                    "sector": row.get("sector") or "",
                    "role_type": row.get("role_type") or "",
                    "channel": row.get("channel") or "",
                    "fit_rating": int(row["fit_rating"]) if str(row.get("fit_rating") or "").strip().isdigit() else None,
                    "source_url": row.get("source") or "",
                    "deadline": parse_date(row.get("deadline")),
                    "notes": row.get("notes") or "",
                    "cover_letter_path": row.get("cover_letter_file") or "",
                    "cv_path": row.get("cv_file") or "",
                    "origin": "legacy",
                    **timestamps,
                },
            )
    conn.commit()


def _read_tracker(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.is_file():
        return [], []
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            raw = list(csv.reader(handle))
    except UnicodeDecodeError:
        # A spreadsheet's plain "CSV" save writes the ANSI code page (cp1252 on
        # most Western installs), so any accented company name stops decoding.
        raise StateError(f"{path} is not UTF-8 text - re-save it as CSV UTF-8") from None
    if not raw:
        return [], []
    header = [cell.strip() for cell in raw[0]]
    if header and header[-1] != "deadline":
        header.append("deadline")
    rows = []
    for values in raw[1:]:
        if not any(str(cell).strip() for cell in values):
            continue
        padded = list(values[: len(header)])
        padded.extend([""] * (len(header) - len(padded)))
        rows.append(dict(zip(header, padded)))
    return header, rows


def _read_seen(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    seen = doc.get("seen") if isinstance(doc, dict) else None
    return seen if isinstance(seen, dict) else (doc if isinstance(doc, dict) else {})


def _parse_outcome(path: Path) -> dict:
    """Legacy-only reader for the one-time import; new state never writes here."""
    result = {"status": "", "date_resolved": "", "stages": [], "notes": "", "company": "", "role": ""}
    if not path.is_file():
        return result
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return result
    title = re.search(r"^#\s+Outcome:\s*(.+?)\s+[—–-]\s+(.+?)\s*$", text, re.MULTILINE)
    if title:
        result["company"] = title.group(1).strip()
        result["role"] = title.group(2).strip()
    match = re.search(r"\*\*Status:\*\*\s*(\S+)", text)
    if match:
        result["status"] = canonical_status(match.group(1))
    match = re.search(r"\*\*Date resolved:\*\*\s*(\d{4}-\d{2}-\d{2})", text)
    if match:
        result["date_resolved"] = match.group(1)
    for match in re.finditer(r"-\s*\[[xX]\]\s*([^\n(]+?)(?:\s*\((\d{4}-\d{2}-\d{2})\))?\s*$", text, re.MULTILINE):
        label = match.group(1).strip()
        stage = STAGE_ALIASES.get(label.casefold())
        if stage:
            result["stages"].append((stage, match.group(2) or ""))
    return result


def _parse_posting_title(path: Path) -> tuple[str, str]:
    if not path.is_file():
        return "", ""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "", ""
    for line in text.splitlines():
        if not line.startswith("# "):
            continue
        title = line[2:].strip()
        if " — " in title:
            role, company = title.split(" — ", 1)
            return company.strip(), role.strip()
        if " - " in title:
            role, company = title.split(" - ", 1)
            return company.strip(), role.strip()
        break
    return "", ""


def _ensure_current_cv(conn: sqlite3.Connection, base: Path) -> int | None:
    path = base / "cv" / "main_example.tex"
    if not path.is_file():
        return None
    row = conn.execute("SELECT id FROM cv_versions WHERE is_current = 1 ORDER BY id DESC LIMIT 1").fetchone()
    if row:
        return int(row["id"])
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    cursor = conn.execute(
        "INSERT INTO cv_versions (label, path, sha256, created_at, is_current) VALUES (?, ?, ?, ?, 1)",
        ("master", path.relative_to(base).as_posix(), digest, _now()),
    )
    return int(cursor.lastrowid)


def import_legacy(
    *,
    repo: Path | str | None = None,
    tracker: Path | str | None = None,
    seen: Path | str | None = None,
    applications: Path | str | None = None,
    force: bool = False,
) -> dict:
    base = Path(repo) if repo else ROOT
    path = init_db(base)
    conn = connect(path)
    try:
        existing = conn.execute("SELECT COUNT(*) FROM applications").fetchone()[0]
        if existing and not force:
            raise StateError("database already contains applications; use --force to import anyway")
        tracker_path = Path(tracker) if tracker else base / "job_search_tracker.csv"
        seen_path = Path(seen) if seen else base / "job_scraper" / "seen_jobs.json"
        apps_dir = Path(applications) if applications else base / "documents" / "applications"
        cv_id = _ensure_current_cv(conn, base)
        jobs = _read_seen(seen_path)
        job_keys_by_url: dict[str, str] = {}
        for raw_key, entry in jobs.items():
            if not isinstance(entry, dict):
                continue
            item = dict(entry)
            item.setdefault("key", str(raw_key))
            job_key = str(item.get("key") or raw_key)
            upsert_job(conn, item, key=job_key)
            normalized = url_norm(item.get("url"))
            if normalized:
                job_keys_by_url[normalized] = job_key
        conn.commit()
        _, rows = _read_tracker(tracker_path)
        report = {
            "jobs": len(jobs),
            "applications": 0,
            "archives": 0,
            "outcomes": 0,
            "conflicts": [],
            "unmatched_archives": [],
            "cover_letter_unknown": 0,
            "cv_version_unknown": 0,
        }
        imported_stems: set[str] = set()
        for row in rows:
            company = str(row.get("company") or "").strip()
            role = str(row.get("role") or "").strip()
            if not company and not role:
                continue
            source = str(row.get("source") or "").strip()
            job_key = job_keys_by_url.get(url_norm(source))
            if job_key is None and company and role:
                candidates = conn.execute(
                    "SELECT job_key FROM jobs WHERE company_norm = ? AND title = ? ORDER BY first_seen DESC LIMIT 1",
                    (norm(company), role),
                ).fetchall()
                if candidates:
                    job_key = candidates[0]["job_key"]
            status_value = canonical_status(row.get("status"))
            if status_value == "unknown":
                status_value = "unknown"
            stem = archive_stem(company, role)
            archive_path = ""
            outcome_note = ""
            outcome = {"status": "", "date_resolved": "", "stages": []}
            if stem and (apps_dir / stem).is_dir():
                archive_path = (apps_dir / stem).relative_to(base).as_posix()
                imported_stems.add(stem)
                outcome_path = apps_dir / stem / "outcome.md"
                if outcome_path.is_file():
                    outcome_note = outcome_path.relative_to(base).as_posix()
                    outcome = _parse_outcome(outcome_path)
                    report["outcomes"] += 1
            if outcome.get("status") and outcome["status"] != "unknown":
                if status_value != outcome["status"]:
                    report["conflicts"].append(
                        {"company": company, "role": role, "tracker": status_value, "outcome": outcome["status"]}
                    )
                if status_value in {"unknown", "applied"}:
                    status_value = outcome["status"]
            cover_path = str(row.get("cover_letter_file") or "").strip()
            if not cover_path and stem:
                for candidate in sorted((apps_dir / stem).glob("cover_letter.*")) if (apps_dir / stem).is_dir() else []:
                    cover_path = candidate.relative_to(base).as_posix()
                    break
            cv_path = str(row.get("cv_file") or "").strip()
            if not cv_path and stem:
                for candidate in sorted((apps_dir / stem).glob("cv_draft.*")) if (apps_dir / stem).is_dir() else []:
                    cv_path = candidate.relative_to(base).as_posix()
                    break
            applied = parse_date(row.get("date"))
            if status_value in {"drafted", "unknown"}:
                applied = None
            date_resolved = outcome.get("date_resolved") or None
            app_id = _insert_application(
                conn,
                {
                    "applied_on": applied,
                    "status": status_value,
                    "company": company,
                    "role": role,
                    "sector": row.get("sector") or "",
                    "role_type": row.get("role_type") or "",
                    "channel": row.get("channel") or "",
                    "contact_person": row.get("contact_person") or "",
                    "fit_rating": int(row["fit_rating"]) if str(row.get("fit_rating") or "").strip().isdigit() else None,
                    "source_url": source,
                    "deadline": parse_date(row.get("deadline")),
                    "notes": row.get("notes") or "",
                    "cover_letter_used": "unknown",
                    "cover_letter_path": cover_path,
                    "cv_path": cv_path,
                    "cv_version_id": None,
                    "first_response_date": None,
                    "date_resolved": date_resolved,
                    "job_key": job_key,
                    "archive_path": archive_path,
                    "outcome_note_path": outcome_note,
                    "origin": "legacy",
                },
            )
            for stage, when in outcome.get("stages", []):
                _set_stage(conn, app_id, stage, True, when, "legacy")
            report["applications"] += 1
            report["cover_letter_unknown"] += 1
            report["cv_version_unknown"] += 1
        if apps_dir.is_dir():
            for folder in sorted(path for path in apps_dir.iterdir() if path.is_dir()):
                if folder.name in imported_stems:
                    continue
                outcome = _parse_outcome(folder / "outcome.md")
                status_value = outcome.get("status") or "unknown"
                company = outcome.get("company") or ""
                role = outcome.get("role") or ""
                if not company or not role:
                    posting_company, posting_role = _parse_posting_title(folder / "job_posting.md")
                    company = company or posting_company
                    role = role or posting_role
                if not company or not role:
                    company = company or folder.name
                    if not role and "_" in folder.name:
                        company, role = folder.name.split("_", 1)
                report["unmatched_archives"].append(folder.name)
                app_id = _insert_application(
                    conn,
                    {
                        "applied_on": None,
                        "status": status_value if status_value in {"hired", "rejected", "no_response", "offer_declined", "withdrawn", "interview_only"} else "unknown",
                        "company": company,
                        "role": role,
                        "date_resolved": outcome.get("date_resolved") or None,
                        "notes": "импортировано из архива без строки трекера",
                        "cover_letter_used": "unknown",
                        "cover_letter_path": next((p.relative_to(base).as_posix() for p in sorted(folder.glob("cover_letter.*"))), ""),
                        "cv_path": next((p.relative_to(base).as_posix() for p in sorted(folder.glob("cv_draft.*"))), ""),
                        "archive_path": folder.relative_to(base).as_posix(),
                        "outcome_note_path": (folder / "outcome.md").relative_to(base).as_posix() if (folder / "outcome.md").is_file() else "",
                        "origin": "legacy_archive",
                    },
                )
                for stage, when in outcome.get("stages", []):
                    _set_stage(conn, app_id, stage, True, when, "legacy")
                report["applications"] += 1
                if (folder / "outcome.md").is_file():
                    report["outcomes"] += 1
                report["cover_letter_unknown"] += 1
                report["cv_version_unknown"] += 1
        backfill_phase0(conn, base)
        conn.commit()
        report["archives"] = len([path for path in apps_dir.iterdir() if path.is_dir()]) if apps_dir.is_dir() else 0
        report_path = base / "state" / "import-report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return report
    finally:
        conn.close()

__all__ = [name for name in globals() if not name.startswith("__")]
