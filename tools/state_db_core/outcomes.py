"""Application draft, outcome, note, and event workflows."""

from __future__ import annotations

import re

from .common import *
from .db import applications_dir
from .applications import *
from .jobs import *

def current_cv(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute(
        "SELECT * FROM cv_versions WHERE is_current = 1 ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return dict(row) if row else None


def record_draft(
    conn: sqlite3.Connection,
    *,
    company: str,
    role: str,
    fit: int,
    letter: str,
    source: str = "",
    deadline: str = "",
    channel: str = "",
    sector: str = "",
    role_type: str = "",
    contact: str = "",
    notes: str = "",
    posting_file: str | None = None,
    cv_version_id: int | None = None,
    cv_path: str = "",
    today: str | None = None,
    repo: Path | str | None = None,
) -> dict:
    source = str(source or "").strip()
    company = str(company or "").strip()
    role = str(role or "").strip()
    if source and (not company or not role):
        matches = _applications_by_url(conn, source)
        if matches:
            company = company or str(matches[0].get("company") or "")
            role = role or str(matches[0].get("role") or "")
        else:
            job = _job_by_url(conn, source)
            if job:
                company = company or str(job.get("company") or "")
                role = role or str(job.get("title") or "")
    if not company or not role:
        raise StateError("company and role are required (or provide a URL known in jobs/applications)")
    try:
        fit_value = int(str(fit).strip())
    except (TypeError, ValueError):
        raise StateError("fit must be an integer 0-100") from None
    if not 0 <= fit_value <= 100:
        raise StateError("fit must be an integer 0-100")
    if cv_version_id is None:
        current = current_cv(conn)
        if current:
            cv_version_id = int(current["id"])
    letter_path = Path(letter)
    if not letter_path.is_file():
        raise StateError(f"cover letter not found: {letter}")
    if deadline:
        deadline = parse_date(deadline) or ""
        if not deadline:
            raise StateError(f"deadline must be YYYY-MM-DD: {deadline!r}")
    today = parse_date(today or _today()) or _today()
    base = Path(repo) if repo else ROOT
    existing = find_application(conn, company=company, role=role)
    if existing and canonical_status(existing.get("status")) in FINAL_STATUSES:
        existing = None
    from tools.letter_check import body_word_count

    try:
        letter_words = body_word_count(letter_path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        letter_words = None
    source_job = None
    if source:
        source_job = conn.execute(
            "SELECT * FROM jobs WHERE url_norm=? ORDER BY first_seen DESC LIMIT 1",
            (url_norm(source),),
        ).fetchone()
    action = "updated" if existing else "appended"
    if existing:
        app_id = int(existing["id"])
        current_status = canonical_status(existing.get("status"))
        updates = {
            "cover_letter_path": letter_path.as_posix(),
            "fit_rating": fit_value,
            "source_url": source or str(existing.get("source_url") or ""),
            "updated_at": _now(),
        }
        if letter_words is not None:
            updates["cover_letter_words"] = letter_words
        if source_job is not None and not existing.get("job_key"):
            updates["job_key"] = source_job["job_key"]
        if deadline:
            updates["deadline"] = deadline
        note = "redrafted" if "redrafted" not in str(existing.get("notes") or "").casefold() else ""
        if note:
            updates["notes"] = _append_note(existing.get("notes"), note)
        if cv_version_id is not None:
            updates["cv_version_id"] = cv_version_id
        if cv_path:
            updates["cv_path"] = cv_path
        conn.execute(
            "UPDATE applications SET " + ", ".join(f"{key}=?" for key in updates) + " WHERE id=?",
            [*updates.values(), app_id],
        )
    else:
        app_id = _insert_application(
            conn,
            {
                "applied_on": None,
                "status": "drafted",
                "company": company,
                "role": role,
                "sector": sector,
                "role_type": role_type,
                "channel": channel,
                "contact_person": contact,
                "fit_rating": fit_value,
                "source_url": source,
                "deadline": deadline or None,
                "notes": notes or f"черновик подготовлен (drafter-reviewer); fit {fit_value}/100; отклик не отправлен",
                "cover_letter_used": "unknown",
                "cover_letter_path": letter_path.as_posix(),
                "cover_letter_words": letter_words,
                "cv_version_id": cv_version_id,
                "cv_path": cv_path,
                "job_key": source_job["job_key"] if source_job is not None else None,
                "origin": "apply",
                "created_at": f"{today}T00:00:00+00:00",
                "updated_at": f"{today}T00:00:00+00:00",
            },
        )
    _ensure_vacancy_source(conn, app_id, source or (existing or {}).get("source_url"))
    stem = archive_stem(company, role)
    target = applications_dir(base) / stem / "job_posting.md" if stem else None
    archive_action = "skipped"
    archive_path = ""
    if target is not None and target.is_file():
        archive_action = "exists"
        archive_path = target.parent.relative_to(base).as_posix()
    elif posting_file:
        source_path = Path(posting_file)
        if target is not None and source_path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(source_path.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
            archive_action = "written"
            archive_path = target.parent.relative_to(base).as_posix()
        else:
            archive_action = "missing"
    if archive_path:
        conn.execute("UPDATE applications SET archive_path=?, updated_at=? WHERE id=?", (archive_path, _now(), app_id))
    posting_path = target if target is not None and target.is_file() else (
        Path(posting_file) if posting_file and Path(posting_file).is_file() else None
    )
    if posting_path is not None:
        job = None
        app_row = _application_row(conn, app_id) or {}
        if app_row.get("job_key"):
            job = _job_row(conn, str(app_row["job_key"]))
        if job is None and source_job is not None:
            job = dict(source_job)
        if job is not None:
            _set_job_description(
                conn,
                job,
                posting_path.read_text(encoding="utf-8", errors="replace"),
                posting_path,
                replace=True,
            )
    conn.commit()
    row = _application_row(conn, app_id) or {}
    return {"action": action, "row": row, "archive": archive_action, "archive_path": archive_path, "id": app_id}


def record_outcome(
    conn: sqlite3.Connection,
    *,
    company: str,
    role: str,
    status: str,
    source: str = "",
    applied_on: str = "",
    first_response_date: str = "",
    date_resolved: str = "",
    cover_letter_used: str = "",
    cv_version_id: int | None = None,
    cv_path: str = "",
    stages: list[str] | None = None,
    note: str = "",
    archive_path: str = "",
    outcome_note_path: str = "",
    create: bool = True,
) -> dict:
    company = str(company or "").strip()
    role = str(role or "").strip()
    if not company or not role:
        raise StateError("company and role are required")
    canonical = canonical_status(status)
    if canonical == "unknown":
        raise StateError(f"unknown status: {status!r}")
    existing = find_application(conn, company=company, role=role)
    applied_text = str(applied_on or "").strip()
    applied_unknown = applied_text.casefold() in {"unknown", "n/a", "неизвестно"}
    if applied_text and not applied_unknown and not parse_date(applied_text):
        raise StateError(f"applied_on must be YYYY-MM-DD or 'unknown': {applied_on!r}")
    if existing is None:
        if not create:
            raise StateError(f"application not found: {company} / {role}")
        resolved = parse_date(date_resolved)
        submitted = None if applied_unknown else parse_date(applied_text)
        app_id = _insert_application(
            conn,
            {
                "applied_on": submitted,
                "status": canonical,
                "company": company,
                "role": role,
                "source_url": source,
                "date_resolved": resolved if canonical in FINAL_STATUSES else None,
                "first_response_date": parse_date(first_response_date),
                "cover_letter_used": canonical_cover_letter(cover_letter_used),
                "cv_version_id": cv_version_id,
                "cv_path": cv_path,
                "archive_path": archive_path,
                "outcome_note_path": outcome_note_path,
                "origin": "outcome",
            },
        )
    else:
        app_id = int(existing["id"])
        updates = {"status": canonical, "updated_at": _now()}
        if source:
            updates["source_url"] = source
        if applied_unknown:
            updates["applied_on"] = None
        elif applied_text:
            updates["applied_on"] = parse_date(applied_text)
        if first_response_date:
            updates["first_response_date"] = parse_date(first_response_date)
        if date_resolved:
            updates["date_resolved"] = parse_date(date_resolved)
        if cover_letter_used:
            updates["cover_letter_used"] = canonical_cover_letter(cover_letter_used)
        if cv_version_id is not None:
            updates["cv_version_id"] = cv_version_id
        if cv_path:
            updates["cv_path"] = cv_path
        if archive_path:
            updates["archive_path"] = archive_path
        if outcome_note_path:
            updates["outcome_note_path"] = outcome_note_path
        conn.execute(
            "UPDATE applications SET " + ", ".join(f"{key}=?" for key in updates) + " WHERE id=?",
            [*updates.values(), app_id],
        )
    for stage in stages or []:
        when = None
        label = str(stage).strip()
        match = re.search(r"\((\d{4}-\d{2}-\d{2})\)\s*$", label)
        if match:
            when = match.group(1)
            label = label[: match.start()].strip()
        _set_stage(conn, app_id, label, True, when, "outcome")
    _sync_application_events(
        conn,
        app_id,
        before=existing,
        source="outcome",
        note=note,
        today=_today(),
    )
    conn.commit()
    row = _application_row(conn, app_id) or {}
    return {"id": app_id, "row": _application_payload(conn, row)}


def add_application_note(
    conn: sqlite3.Connection,
    *,
    company: str,
    role: str,
    note: str,
    event_date: str | None = None,
    source: str = "manual",
) -> dict:
    existing = find_application(conn, company=company, role=role)
    if not existing:
        raise StateError(f"application not found: {company} / {role}")
    app_id = int(existing["id"])
    text = " ".join(str(note or "").split())
    if not text:
        raise StateError("note is empty")
    conn.execute(
        "UPDATE applications SET updated_at=? WHERE id=?",
        (_now(), app_id),
    )
    _sync_application_events(
        conn,
        app_id,
        source=source,
        note=text,
        today=parse_date(event_date) or _today(),
    )
    conn.commit()
    return {"id": app_id, "row": _application_payload(conn, _application_row(conn, app_id) or {})}


def update_application_event(
    conn: sqlite3.Connection,
    *,
    event_id: int,
    event_date: str,
    application_id: int | None = None,
    text: str = "",
) -> dict:
    parsed = parse_date(event_date)
    if not parsed:
        raise StateError(f"event_date must be YYYY-MM-DD: {event_date!r}")
    row = conn.execute(
        "SELECT * FROM application_events WHERE id=?",
        (int(event_id),),
    ).fetchone()
    if row is None:
        raise StateError(f"application event not found: {event_id}")
    event = dict(row)
    app_id = int(event["application_id"])
    if application_id is not None and app_id != int(application_id):
        raise StateError(
            f"application event {event_id} belongs to application {app_id}, "
            f"not {application_id}"
        )
    old_date = parse_date(event.get("event_date"))
    old_text = str(event.get("text") or "")
    new_text = " ".join(str(text).split()) if text else old_text
    conn.execute(
        "UPDATE application_events SET event_date=?, text=? WHERE id=?",
        (parsed, new_text, int(event_id)),
    )
    if old_date and old_date != parsed:
        application = conn.execute(
            "SELECT notes FROM applications WHERE id=?",
            (app_id,),
        ).fetchone()
        notes = str(application["notes"] or "") if application else ""
        old_fragment = f"{old_date}: {old_text}"
        new_fragment = f"{parsed}: {new_text}"
        if old_text and old_fragment in notes:
            notes = notes.replace(old_fragment, new_fragment, 1)
        elif f"{old_date}: " in notes:
            notes = notes.replace(f"{old_date}: ", f"{parsed}: ", 1)
        if application and notes != str(application["notes"] or ""):
            conn.execute(
                "UPDATE applications SET notes=?, updated_at=? WHERE id=?",
                (notes, _now(), app_id),
            )
    conn.commit()
    return {
        "status": "ok",
        "event_id": int(event_id),
        "application_id": app_id,
        "event_date": parsed,
        "text": new_text,
    }


def delete_application_event(
    conn: sqlite3.Connection,
    *,
    event_id: int,
    application_id: int | None = None,
) -> dict:
    row = conn.execute(
        "SELECT * FROM application_events WHERE id=?",
        (int(event_id),),
    ).fetchone()
    if row is None:
        raise StateError(f"application event not found: {event_id}")
    event = dict(row)
    app_id = int(event["application_id"])
    if application_id is not None and app_id != int(application_id):
        raise StateError(
            f"application event {event_id} belongs to application {app_id}, "
            f"not {application_id}"
        )
    conn.execute("DELETE FROM application_events WHERE id=?", (int(event_id),))
    if event.get("event_type") == "note" and event.get("text"):
        application = conn.execute(
            "SELECT notes FROM applications WHERE id=?", (app_id,)
        ).fetchone()
        notes = str(application["notes"] or "") if application else ""
        fragment = f"{event['event_date']}: {event['text']}"
        if fragment in notes:
            notes = " ".join(notes.replace(fragment, "", 1).split())
            conn.execute(
                "UPDATE applications SET notes=?, updated_at=? WHERE id=?",
                (notes, _now(), app_id),
            )
    conn.commit()
    return {
        "status": "ok",
        "event_id": int(event_id),
        "application_id": app_id,
    }


def list_applications(conn: sqlite3.Connection, open_only: bool = False) -> list[dict]:
    rows = [
        dict(row)
        for row in conn.execute("SELECT * FROM applications ORDER BY COALESCE(applied_on, created_at) DESC, id DESC")
    ]
    if open_only:
        rows = [row for row in rows if canonical_status(row.get("status")) not in FINAL_STATUSES and canonical_status(row.get("status")) != "drafted"]
    return [_application_payload(conn, row) for row in rows]

__all__ = [name for name in globals() if not name.startswith("__")]
