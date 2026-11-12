"""Application rows, stages, events, sources, and sync state."""

from __future__ import annotations

import json
import re
import sqlite3

from .common import *
from .jobs import *

def _application_row(conn: sqlite3.Connection, application_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM applications WHERE id = ?", (application_id,)).fetchone()
    return dict(row) if row else None


def _application_payload(conn: sqlite3.Connection, row: sqlite3.Row | dict) -> dict:
    result = dict(row)
    for field, source in (("strengths", "strengths_json"), ("gaps", "gaps_json")):
        if source in result:
            result[field] = _load_json(result[source], [])
    stages = conn.execute(
        "SELECT stage, reached, date, source FROM application_stages WHERE application_id = ? ORDER BY stage",
        (result.get("id"),),
    ).fetchall()
    result["stages"] = [dict(stage) for stage in stages]
    return result


def find_application(
    conn: sqlite3.Connection,
    *,
    source: str = "",
    company: str = "",
    role: str = "",
    target_id: str | None = None,
) -> dict | None:
    if source:
        normalized = url_norm(source)
        rows = [
            dict(row)
            for row in conn.execute("SELECT * FROM applications ORDER BY applied_on DESC, id DESC")
        ]
        matches = [row for row in rows if normalized and url_norm(row.get("source_url")) == normalized]
        if matches:
            open_matches = [row for row in matches if canonical_status(row.get("status")) not in FINAL_STATUSES]
            chosen = (open_matches or matches)[0]
            return _application_payload(conn, chosen)
    if target_id:
        rows = [
            dict(row)
            for row in conn.execute("SELECT * FROM applications ORDER BY applied_on DESC, id DESC")
        ]
        matches = []
        for row in rows:
            match = re.search(r"/vacancy/(\d+)", str(row.get("source_url") or ""))
            if match and match.group(1) == str(target_id):
                matches.append(row)
        if matches:
            open_matches = [row for row in matches if canonical_status(row.get("status")) not in FINAL_STATUSES]
            return _application_payload(conn, (open_matches or matches)[0])
    company_norm = norm(company)
    if not company_norm:
        return None
    role_norm = norm(role)
    rows = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM applications WHERE company_norm = ? ORDER BY applied_on DESC, id DESC",
            (company_norm,),
        )
    ]
    for row in rows:
        if role_norm and row.get("role_norm") != role_norm:
            continue
        if source and row.get("source_url"):
            continue
        return _application_payload(conn, row)
    return None


def _job_public(conn: sqlite3.Connection, key: str | None) -> dict | None:
    if not key:
        return None
    row = conn.execute("SELECT * FROM jobs WHERE job_key = ?", (key,)).fetchone()
    if not row:
        return None
    job = dict(row)
    return {
        "job_key": job.get("job_key"),
        "title": job.get("title"),
        "company": job.get("company"),
        "url": job.get("url"),
        "status": job.get("status"),
        "rank_score": job.get("rank_score"),
        "rank_verdict": job.get("rank_verdict"),
        "deadline": job.get("deadline"),
        "posted_date": job.get("posted_date"),
        "portal": job.get("portal"),
    }


def _application_public(conn: sqlite3.Connection, row: sqlite3.Row | dict) -> dict:
    app = _application_payload(conn, row)
    last_event = conn.execute(
        "SELECT event_date, event_type, text FROM application_events "
        "WHERE application_id = ? ORDER BY COALESCE(event_date, '') DESC, id DESC LIMIT 1",
        (app.get("id"),),
    ).fetchone()
    return {
        "id": app.get("id"),
        "company": app.get("company"),
        "role": app.get("role"),
        "status": app.get("status"),
        "applied_on": app.get("applied_on"),
        "date_resolved": app.get("date_resolved"),
        "first_response_date": app.get("first_response_date"),
        "fit_rating": app.get("fit_rating"),
        "source_url": app.get("source_url"),
        "cover_letter_used": app.get("cover_letter_used"),
        "cover_letter_path": app.get("cover_letter_path"),
        "cv_version_id": app.get("cv_version_id"),
        "cv_path": app.get("cv_path"),
        "job_key": app.get("job_key"),
        "archive_path": app.get("archive_path"),
        "outcome_note_path": app.get("outcome_note_path"),
        "origin": app.get("origin"),
        "stages": app.get("stages", []),
        "sources": list_application_sources(conn, int(app.get("id"))),
        "last_event": dict(last_event) if last_event else None,
    }


def _applications_by_url(conn: sqlite3.Connection, url: str) -> list[dict]:
    normalized = url_norm(url)
    if not normalized:
        return []
    rows = [
        dict(row)
        for row in conn.execute("SELECT * FROM applications ORDER BY applied_on DESC, id DESC")
    ]
    return [row for row in rows if url_norm(row.get("source_url")) == normalized]


def _job_by_url(conn: sqlite3.Connection, url: str) -> dict | None:
    normalized = url_norm(url)
    if not normalized:
        return None
    rows = [dict(row) for row in conn.execute("SELECT * FROM jobs")]
    matches = [row for row in rows if url_norm(row.get("url")) == normalized]
    return matches[0] if matches else None


def _match_candidates(rows: list[dict]) -> list[dict]:
    return [
        {
            "id": row.get("id"),
            "company": row.get("company"),
            "role": row.get("role"),
            "status": row.get("status"),
            "applied_on": row.get("applied_on"),
        }
        for row in rows
    ]


def application_show(
    conn: sqlite3.Connection,
    *,
    url: str = "",
    application_id: int | None = None,
) -> dict:
    if application_id is not None:
        row = _application_row(conn, int(application_id))
        if row is None:
            raise StateError(f"application not found: {application_id}")
        return {
            "status": "ok",
            "matched_by": "id",
            "ambiguous": False,
            "application": _application_public(conn, row),
            "job": _job_public(conn, row.get("job_key")),
        }
    if not url:
        raise StateError("application-show needs --url or --application-id")
    matches = _applications_by_url(conn, url)
    if len(matches) > 1:
        return {
            "status": "ambiguous",
            "matched_by": "url",
            "ambiguous": True,
            "matches": _match_candidates(matches),
            "application": None,
            "job": None,
        }
    if matches:
        row = matches[0]
        return {
            "status": "ok",
            "matched_by": "url",
            "ambiguous": False,
            "application": _application_public(conn, row),
            "job": _job_public(conn, row.get("job_key")),
        }
    job = _job_by_url(conn, url)
    return {
        "status": "job_only" if job else "not_found",
        "matched_by": "url",
        "ambiguous": False,
        "application": None,
        "job": _job_public(conn, job.get("job_key")) if job else None,
    }


def _parse_stage_arg(value: str) -> tuple[str, str | None]:
    label = str(value or "").strip()
    when = None
    match = re.search(r"\((\d{4}-\d{2}-\d{2})\)\s*$", label)
    if match:
        when = match.group(1)
        label = label[: match.start()].strip()
    normalized = STAGE_ALIASES.get(label.casefold().replace("_", " "), label.casefold())
    if normalized not in STAGES:
        raise StateError(f"unknown stage: {value!r}; use phone screen, technical, technical 2, case, final, or offer")
    if when and not parse_date(when):
        raise StateError(f"stage date must be YYYY-MM-DD: {when!r}")
    return normalized, when


def application_update(
    conn: sqlite3.Connection,
    *,
    url: str = "",
    application_id: int | None = None,
    status: str = "",
    cover_letter_used: str = "",
    applied_on: str = "",
    first_response_date: str = "",
    date_resolved: str = "",
    stages: list[str] | None = None,
    note: str = "",
    cv_version_id: int | None = None,
    cv_path: str = "",
    archive_path: str = "",
    outcome_note_path: str = "",
    today: str | None = None,
) -> dict:
    today_value = parse_date(today or _today()) or _today()
    if application_id is not None:
        row = _application_row(conn, int(application_id))
        if row is None:
            raise StateError(f"application not found: {application_id}")
        matched_by = "id"
    elif url:
        matches = _applications_by_url(conn, url)
        if not matches:
            raise StateError(f"application not found for URL: {url}")
        if len(matches) > 1:
            ids = ", ".join(str(item.get("id")) for item in matches)
            raise StateError(f"ambiguous URL; use --application-id ({ids})")
        row = matches[0]
        matched_by = "url"
    else:
        raise StateError("application-update needs --url or --application-id")

    stage_args = stages or []
    if not any(
        (
            status, cover_letter_used, applied_on, first_response_date,
            date_resolved, stage_args, note, cv_version_id, cv_path,
            archive_path, outcome_note_path,
        )
    ):
        raise StateError("application-update needs at least one field to change")

    old = dict(row)
    updates: dict[str, object] = {}
    new_status = canonical_status(status) if status else canonical_status(old.get("status"))
    if status:
        if new_status == "unknown":
            raise StateError(f"unknown status: {status!r}")
        updates["status"] = new_status
    applied_text = str(applied_on or "").strip()
    applied_unknown = applied_text.casefold() in {"unknown", "n/a", "неизвестно"}
    if applied_unknown:
        updates["applied_on"] = None
    elif applied_text:
        parsed = parse_date(applied_text)
        if not parsed:
            raise StateError(f"applied_on must be YYYY-MM-DD or 'unknown': {applied_on!r}")
        updates["applied_on"] = parsed
    elif (
        status
        and canonical_status(old.get("status")) == "drafted"
        and new_status != "drafted"
        and not old.get("applied_on")
    ):
        updates["applied_on"] = today_value
    if first_response_date:
        parsed = parse_date(first_response_date)
        if not parsed:
            raise StateError(f"first_response_date must be YYYY-MM-DD: {first_response_date!r}")
        updates["first_response_date"] = parsed
    if date_resolved:
        parsed = parse_date(date_resolved)
        if not parsed:
            raise StateError(f"date_resolved must be YYYY-MM-DD: {date_resolved!r}")
        updates["date_resolved"] = parsed
    elif status and new_status in FINAL_STATUSES and not old.get("date_resolved"):
        updates["date_resolved"] = today_value
    if cover_letter_used:
        value = canonical_cover_letter(cover_letter_used)
        if value == "unknown" and str(cover_letter_used).strip().casefold() not in {"unknown", ""}:
            raise StateError(f"unknown cover_letter_used: {cover_letter_used!r}")
        updates["cover_letter_used"] = value
    if cv_version_id is not None:
        if not conn.execute("SELECT 1 FROM cv_versions WHERE id = ?", (int(cv_version_id),)).fetchone():
            raise StateError(f"cv_version not found: {cv_version_id}")
        updates["cv_version_id"] = int(cv_version_id)
    if cv_path:
        updates["cv_path"] = cv_path
    if archive_path:
        updates["archive_path"] = archive_path
    if outcome_note_path:
        updates["outcome_note_path"] = outcome_note_path
    if updates:
        updates["updated_at"] = _now()
        conn.execute(
            "UPDATE applications SET " + ", ".join(f"{key}=?" for key in updates) + " WHERE id=?",
            [*updates.values(), old["id"]],
        )
    changed = [key for key, value in updates.items() if key != "updated_at" and old.get(key) != value]
    for stage in stage_args:
        normalized, when = _parse_stage_arg(stage)
        _set_stage(conn, int(old["id"]), normalized, True, when, "application-update")
        changed.append(f"stage:{normalized}")
    _sync_application_events(
        conn,
        int(old["id"]),
        before=old,
        source="application-update",
        note=note,
        today=today_value,
    )
    conn.commit()
    refreshed = _application_row(conn, int(old["id"])) or {}
    return {
        "status": "ok",
        "matched_by": matched_by,
        "application_id": old["id"],
        "changed": changed,
        "application": _application_public(conn, refreshed),
        "job": _job_public(conn, refreshed.get("job_key")),
    }


def _insert_application(conn: sqlite3.Connection, values: dict) -> int:
    now = _now()
    values = dict(values)
    values.setdefault("created_at", now)
    values.setdefault("updated_at", now)
    values.setdefault("status", "drafted")
    values.setdefault("cover_letter_used", "unknown")
    values.setdefault("origin", "legacy")
    values["company_norm"] = norm(values.get("company"))
    values["role_norm"] = norm(values.get("role"))
    columns = list(values)
    cursor = conn.execute(
        f"INSERT INTO applications ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
        [values[column] for column in columns],
    )
    app_id = int(cursor.lastrowid)
    _ensure_vacancy_source(conn, app_id, values.get("source_url"))
    return app_id


def _set_stage(conn: sqlite3.Connection, application_id: int, stage: str, reached: bool, when: str | None = None, source: str = "") -> None:
    normalized = STAGE_ALIASES.get(stage.strip().casefold().replace("_", " "), stage.strip().casefold())
    if normalized not in STAGES:
        return
    conn.execute(
        "INSERT INTO application_stages (application_id, stage, reached, date, source) "
        "VALUES (?, ?, ?, ?, ?) ON CONFLICT(application_id, stage) DO UPDATE SET "
        "reached=excluded.reached, date=COALESCE(excluded.date, application_stages.date), "
        "source=excluded.source",
        (application_id, normalized, 1 if reached else 0, parse_date(when), source),
    )


def _append_note(existing: str, note: str) -> str:
    note = " ".join(str(note or "").split())
    existing = str(existing or "").strip()
    if not note:
        return existing
    return f"{existing} {note}".strip() if existing else note


def _ensure_vacancy_source(
    conn: sqlite3.Connection, application_id: int, source_url: object
) -> None:
    vacancy_id = hh_vacancy_id(source_url)
    if not vacancy_id:
        return
    if not conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='application_sources'"
    ).fetchone():
        return
    try:
        conn.execute(
            "INSERT OR IGNORE INTO application_sources "
            "(application_id, source, external_type, external_id, url, last_state, "
            "last_seen_at, metadata_json, created_at, updated_at) "
            "VALUES (?, 'hh', 'vacancy', ?, ?, '', NULL, ?, ?, ?)",
            (
                int(application_id),
                vacancy_id,
                str(source_url or ""),
                json.dumps({"backfill": "applications.source_url"}, ensure_ascii=False),
                _now(),
                _now(),
            ),
        )
    except sqlite3.IntegrityError:
        pass


def _insert_event(
    conn: sqlite3.Connection,
    application_id: int,
    event_type: str,
    *,
    event_date: str | None = None,
    text: str = "",
    source: str = "",
    external_ref: str = "",
    metadata: dict | list | None = None,
    recorded_at: str | None = None,
    dedupe: bool = True,
    dedupe_text: bool = True,
) -> bool:
    if event_type not in EVENT_TYPES:
        raise StateError(f"unknown event type: {event_type!r}")
    day = parse_date(event_date) or _today()
    body = " ".join(str(text or "").split())
    ref = str(external_ref or "").strip()
    if dedupe:
        sql = (
            "SELECT 1 FROM application_events WHERE application_id=? "
            "AND event_type=? AND COALESCE(event_date, '')=? "
            "AND COALESCE(external_ref, '')=?"
        )
        params: list[object] = [application_id, event_type, day, ref]
        if dedupe_text:
            sql += " AND text=?"
            params.append(body)
        if conn.execute(sql, params).fetchone():
            return False
    payload = json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True)
    conn.execute(
        "INSERT INTO application_events "
        "(application_id, event_date, event_type, text, source, recorded_at, external_ref, metadata_json) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (application_id, day, event_type, body, source, recorded_at or _now(), ref, payload),
    )
    return True


def _sync_application_events(
    conn: sqlite3.Connection,
    application_id: int,
    *,
    before: dict | None = None,
    source: str,
    note: str = "",
    today: str | None = None,
    use_today: bool = True,
) -> None:
    after = _application_row(conn, application_id)
    if not after:
        return
    _ensure_vacancy_source(conn, application_id, after.get("source_url"))
    today_value = parse_date(today) or _today()
    old_status = canonical_status(before.get("status")) if before else ""
    status = canonical_status(after.get("status"))
    applied_on = parse_date(after.get("applied_on"))
    first_response = parse_date(after.get("first_response_date"))
    resolved = parse_date(after.get("date_resolved"))
    if applied_on:
        _insert_event(
            conn, application_id, "submitted", event_date=applied_on,
            text="Application submitted", source=source,
        )
    if first_response:
        _insert_event(
            conn, application_id, "response_received", event_date=first_response,
            text="First response received", source=source,
        )
    event_type = STATUS_EVENT_TYPES.get(status, "status_changed")
    status_changed = status != old_status and use_today
    if resolved and status in FINAL_STATUSES and not status_changed:
        _insert_event(
            conn, application_id, event_type, event_date=resolved,
            text=f"Status: {status}", source=source,
        )
    if status_changed:
        event_date = resolved or (applied_on if status == "applied" else today_value)
        _insert_event(
            conn, application_id, event_type, event_date=event_date,
            text=f"Status changed to {status}", source=source,
            dedupe_text=False,
        )
    for stage in conn.execute(
        "SELECT stage, date FROM application_stages "
        "WHERE application_id=? AND reached=1 AND date IS NOT NULL AND date <> ''",
        (application_id,),
    ):
        _insert_event(
            conn, application_id, "stage_reached", event_date=stage["date"],
            text=f"Stage reached: {stage['stage']}", source=source,
            metadata={"stage": stage["stage"]},
        )
    if note:
        _insert_event(
            conn, application_id, "note", event_date=today_value,
            text=note, source=source,
        )


def upsert_application_source(
    conn: sqlite3.Connection,
    application_id: int,
    *,
    source: str,
    external_type: str,
    external_id: str,
    url: str = "",
    last_state: str = "",
    last_seen_at: str | None = None,
    metadata: dict | None = None,
) -> dict:
    if not source or not external_type or not external_id:
        raise StateError("application source requires source, external_type, and external_id")
    if not _application_row(conn, int(application_id)):
        raise StateError(f"application not found: {application_id}")
    now = _now()
    payload = json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True)
    try:
        conn.execute(
            "INSERT INTO application_sources "
            "(application_id, source, external_type, external_id, url, last_state, "
            "last_seen_at, metadata_json, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(application_id, source, external_type, external_id) DO UPDATE SET "
            "url=excluded.url, last_state=excluded.last_state, last_seen_at=excluded.last_seen_at, "
            "metadata_json=excluded.metadata_json, updated_at=excluded.updated_at",
            (
                int(application_id), str(source), str(external_type), str(external_id),
                str(url or ""), str(last_state or ""), last_seen_at, payload, now, now,
            ),
        )
    except sqlite3.IntegrityError as exc:
        raise StateError(
            f"source reference already belongs to another application: {source}/{external_type}/{external_id}"
        ) from exc
    row = conn.execute(
        "SELECT * FROM application_sources WHERE application_id=? "
        "AND source=? AND external_type=? AND external_id=?",
        (int(application_id), str(source), str(external_type), str(external_id)),
    ).fetchone()
    return dict(row) if row else {}


def list_application_sources(conn: sqlite3.Connection, application_id: int) -> list[dict]:
    return [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM application_sources WHERE application_id=? "
            "ORDER BY source, external_type, external_id",
            (int(application_id),),
        )
    ]


def get_sync_state(conn: sqlite3.Connection, source: str) -> dict | None:
    row = conn.execute("SELECT * FROM sync_state WHERE source=?", (str(source),)).fetchone()
    return dict(row) if row else None


def set_sync_state(
    conn: sqlite3.Connection,
    source: str,
    *,
    cursor: str = "",
    metadata: dict | None = None,
    last_sync_at: str | None = None,
) -> dict:
    if not source:
        raise StateError("sync source is required")
    payload = json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True)
    conn.execute(
        "INSERT INTO sync_state (source, cursor, last_sync_at, metadata_json) "
        "VALUES (?, ?, ?, ?) ON CONFLICT(source) DO UPDATE SET "
        "cursor=excluded.cursor, last_sync_at=excluded.last_sync_at, metadata_json=excluded.metadata_json",
        (str(source), str(cursor or ""), last_sync_at or _now(), payload),
    )
    row = conn.execute("SELECT * FROM sync_state WHERE source=?", (str(source),)).fetchone()
    return dict(row) if row else {}


def backfill_phase0(conn: sqlite3.Connection, base: Path | str | None = None) -> dict:
    """Idempotently add source refs and date events for existing applications."""
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    if "application_sources" not in tables:
        return {"sources": 0, "events": 0}
    conn.execute(
        "UPDATE application_events SET event_type='interview_status' "
        "WHERE event_type='interview'"
    )
    source_count = 0
    event_count = 0
    today_value = _today()
    applications = [dict(row) for row in conn.execute("SELECT * FROM applications")]
    for app in applications:
        app_id = int(app["id"])
        before_events = conn.execute("SELECT COUNT(*) FROM application_events WHERE application_id=?", (app_id,)).fetchone()[0]
        before_sources = conn.execute("SELECT COUNT(*) FROM application_sources WHERE application_id=?", (app_id,)).fetchone()[0]
        _sync_application_events(
            conn, app_id, source="migration", today=today_value, use_today=False
        )
        after_events = conn.execute("SELECT COUNT(*) FROM application_events WHERE application_id=?", (app_id,)).fetchone()[0]
        after_sources = conn.execute("SELECT COUNT(*) FROM application_sources WHERE application_id=?", (app_id,)).fetchone()[0]
        event_count += max(0, after_events - before_events)
        source_count += max(0, after_sources - before_sources)
    conn.commit()
    return {"sources": source_count, "events": event_count}

__all__ = [name for name in globals() if not name.startswith("__")]
