"""Legacy outcome.md and application-notes migration."""

from __future__ import annotations

import difflib
import re

from .common import *
from .applications import *
from .migration_jobs import _repair_archive_paths

OUTCOME_DATE_NOTE_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})\s*[:—–-]\s*(?P<text>.+)$"
)
OUTCOME_STAGE_RE = re.compile(
    r"^-\s*\[[xX]\]\s*([^\n(]+?)(?:\s*\((\d{4}-\d{2}-\d{2})\))?\s*$",
    re.MULTILINE,
)

def _parse_outcome_text(text: str) -> dict:
    """Parse the legacy outcome.md shape without treating prose as state."""
    result = {
        "company": "",
        "role": "",
        "status_raw": "",
        "status": "",
        "date_resolved": "",
        "stages": [],
        "dated_notes": [],
        "undated_notes": [],
    }
    title = re.search(r"^#\s+(?:Outcome:\s*)?(.+?)\s+[—–-]\s+(.+?)\s*$", text, re.MULTILINE)
    if title:
        result["company"] = title.group(1).strip()
        result["role"] = title.group(2).strip()
    status = re.search(r"\*\*Status:\*\*\s*([^\n]+)", text)
    if status:
        result["status_raw"] = status.group(1).strip()
        result["status"] = canonical_status(result["status_raw"])
    resolved = re.search(r"\*\*Date resolved:\*\*\s*(\d{4}-\d{2}-\d{2})", text)
    if resolved:
        result["date_resolved"] = resolved.group(1)
    for match in OUTCOME_STAGE_RE.finditer(text):
        label = match.group(1).strip()
        stage = STAGE_ALIASES.get(label.casefold())
        if stage:
            result["stages"].append((stage, match.group(2) or ""))
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("- ") or re.match(r"-\s*\[[ xX]\]", line):
            continue
        body = line[2:].strip()
        note = OUTCOME_DATE_NOTE_RE.match(body)
        if note:
            result["dated_notes"].append(
                {"date": note.group("date"), "text": note.group("text").strip()}
            )
        elif body:
            result["undated_notes"].append(body)
    return result

def _outcome_date_score(app: dict, dates: list[str]) -> int:
    if not dates:
        return 0
    applied = parse_date(app.get("applied_on"))
    resolved = parse_date(app.get("date_resolved"))
    score = 0
    if applied:
        if all(day >= applied for day in dates):
            score += 2
        if applied in dates:
            score += 1
        if any(day < applied for day in dates):
            score -= 3
    if resolved:
        if all(day <= resolved for day in dates):
            score += 1
        if resolved in dates:
            score += 1
    return score


def _application_for_outcome(
    conn: sqlite3.Connection, archive_dir: str, parsed: dict
) -> tuple[dict | None, str]:
    rows = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM applications WHERE archive_path=? OR outcome_note_path=?",
            (archive_dir, f"{archive_dir}/outcome.md"),
        )
    ]
    if not rows:
        return None, "unmatched"
    if len(rows) == 1:
        return rows[0], "archive"
    dates = [note["date"] for note in parsed.get("dated_notes", [])]
    scored = sorted(
        ((_outcome_date_score(row, dates), row) for row in rows),
        key=lambda item: item[0],
        reverse=True,
    )
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None, "ambiguous"
    if scored[0][0] <= 0:
        return None, "ambiguous"
    return scored[0][1], "archive+dates"

def _split_dated_notes(notes: str) -> tuple[str, list[dict]]:
    text = str(notes or "").strip()
    if not text:
        return "", []
    matches = list(re.finditer(r"(?<!\d)(\d{4}-\d{2}-\d{2})\s*[:—–-]\s*", text))
    if not matches:
        return text, []
    prefix = text[: matches[0].start()].strip().rstrip(";,").strip()
    fragments = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        fragment = text[match.start() : end].strip()
        body = fragment[match.end() - match.start() :].strip()
        if body:
            fragments.append({"date": match.group(1), "text": body})
    return prefix, fragments


def _tidy_outcome_text(text: str) -> str:
    lines = text.splitlines()
    compact: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.strip().startswith("## "):
            end = index + 1
            while end < len(lines) and not lines[end].strip().startswith("## "):
                end += 1
            if not any(item.strip() for item in lines[index + 1 : end]):
                index = end
                continue
        compact.append(line)
        index += 1
    cleaned_lines: list[str] = []
    previous_blank = False
    for line in compact:
        blank = not line.strip()
        if blank and previous_blank:
            continue
        cleaned_lines.append(line)
        previous_blank = blank
    cleaned = "\n".join(cleaned_lines).strip()
    body = re.sub(r"^#.*$", "", cleaned, count=1, flags=re.MULTILINE).strip()
    if not body:
        cleaned += (
            "\n\n> Structured status, dates, stages, and dated notes live in "
            "`state/job_search.sqlite`.\n"
        )
    return cleaned + "\n"


def _strip_outcome_text(text: str) -> tuple[str, int]:
    lines = text.splitlines()
    kept: list[str] = []
    removed = 0
    skip_stage_section = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("## "):
            heading = stripped[3:].strip().casefold()
            skip_stage_section = heading in {
                "interview stages reached",
                "этапы собеседований",
                "стадии",
            }
            if skip_stage_section:
                removed += 1
                continue
        if skip_stage_section:
            if stripped.startswith("- [") or stripped.startswith("- ["):
                removed += 1
                continue
            if not stripped:
                continue
            skip_stage_section = False
        if re.match(r"^\*\*(Status|Date resolved):\*\*", stripped, re.IGNORECASE):
            removed += 1
            continue
        if stripped.startswith("- ") and not re.match(r"-\s*\[[ xX]\]", stripped):
            if OUTCOME_DATE_NOTE_RE.match(stripped[2:].strip()):
                removed += 1
                continue
        kept.append(line)
    return _tidy_outcome_text("\n".join(kept)), removed

def backfill_cover_letter_words(
    conn: sqlite3.Connection,
    repo: Path | str | None = None,
    *,
    write: bool = False,
) -> dict:
    from tools.letter_check import body_word_count

    base = Path(repo) if repo else ROOT
    report = {"mode": "write" if write else "dry-run", "scanned": 0, "updated": 0, "skipped": 0, "missing": 0, "details": []}
    for app in conn.execute(
        "SELECT id, company, role, cover_letter_path, archive_path, cover_letter_words FROM applications"
    ):
        row = dict(app)
        if row.get("cover_letter_words") is not None:
            continue
        candidates = []
        if row.get("cover_letter_path"):
            candidates.append(base / row["cover_letter_path"])
        archive = base / _normalize_archive_dir(row.get("archive_path"))
        candidates.extend([archive / "cover_letter.txt", archive / "cover_letter.tex"])
        path = next((item for item in candidates if item.is_file()), None)
        if path is None:
            report["missing"] += 1
            continue
        report["scanned"] += 1
        if path.suffix.casefold() != ".txt":
            report["skipped"] += 1
            report["details"].append({"id": row["id"], "path": path.as_posix(), "reason": "not_plain_text"})
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            report["skipped"] += 1
            continue
        count = body_word_count(text)
        if count <= 0:
            report["skipped"] += 1
            continue
        report["updated"] += 1
        report["details"].append({"id": row["id"], "path": path.as_posix(), "words": count})
        if write:
            conn.execute(
                "UPDATE applications SET cover_letter_words=?, updated_at=? WHERE id=?",
                (count, _now(), row["id"]),
            )
    if write:
        conn.commit()
    return report

def _note_text_key(text: object) -> str:
    value = re.sub(r"^\d{4}-\d{2}-\d{2}\s*[:—–-]\s*", "", str(text or "").strip())
    value = value.casefold().replace("ё", "е")
    value = re.sub(r"[^\w\s]+", " ", value)
    value = re.sub(r"\bобратн\w*\s+связ\w*", "фидбек", value)
    value = re.sub(r"\bфидбек\w*", "фидбек", value)
    value = re.sub(r"\bне\s+сообщ\w*", "не сообщен", value)
    value = re.sub(r"\bтехсобес\w*", "техническое собеседование", value)
    return " ".join(value.split())


def _note_category(text: object) -> str:
    value = str(text or "").casefold().replace("ё", "е")
    if "отказ" in value or "reject" in value:
        return "rejected"
    if "оффер" in value or "offer" in value:
        return "offer"
    if any(word in value for word in ("интервью", "собес", "скрининг", "interview")):
        return "interview"
    if ("отклик" in value or "заявка" in value) and ("отправ" in value or "applied" in value):
        return "submitted"
    if "напомин" in value or "follow" in value:
        return "follow_up"
    return "other"


def _notes_are_duplicates(first: object, second: object) -> bool:
    first_key = _note_text_key(first)
    second_key = _note_text_key(second)
    if not first_key or not second_key:
        return False
    if _note_category(first) != _note_category(second):
        return False
    if first_key in second_key or second_key in first_key:
        return True
    if difflib.SequenceMatcher(None, first_key, second_key).ratio() >= 0.82:
        return True
    first_tokens = set(first_key.split())
    second_tokens = set(second_key.split())
    if not first_tokens or not second_tokens:
        return False
    if (
        first_tokens <= second_tokens or second_tokens <= first_tokens
    ) and min(len(first_tokens), len(second_tokens)) >= 3:
        return True
    return len(first_tokens & second_tokens) / len(first_tokens | second_tokens) >= 0.6


def _dedupe_note_events(conn: sqlite3.Connection, *, write: bool) -> dict:
    rows = [
        dict(row)
        for row in conn.execute(
            "SELECT id, application_id, event_date, text FROM application_events "
            "WHERE event_type='note' ORDER BY application_id, event_date, id"
        )
    ]
    groups: dict[tuple[object, object], list[dict]] = {}
    for row in rows:
        groups.setdefault((row["application_id"], row["event_date"]), []).append(row)
    deleted = []
    for group in groups.values():
        if len(group) < 2:
            continue
        kept: list[tuple[dict, str]] = []
        for row in sorted(group, key=lambda item: (-len(_note_text_key(item["text"])), item["id"])):
            key = _note_text_key(row["text"])
            if not key:
                continue
            duplicate = any(
                _notes_are_duplicates(row["text"], kept_row["text"])
                for kept_row, _ in kept
            )
            if duplicate:
                deleted.append(
                    {
                        "id": row["id"],
                        "application_id": row["application_id"],
                        "event_date": row["event_date"],
                    }
                )
                if write:
                    conn.execute("DELETE FROM application_events WHERE id=?", (row["id"],))
            else:
                kept.append((row, key))
    return {"deleted": len(deleted), "details": deleted}


def migrate_text_state(
    conn: sqlite3.Connection,
    repo: Path | str | None = None,
    *,
    write: bool = False,
    strip_outcome: bool = False,
) -> dict:
    """Move dated outcome notes into events and remove duplicated legacy state."""
    base = Path(repo) if repo else ROOT
    report = {
        "mode": "write" if write else "dry-run",
        "outcomes": 0,
        "mapped": 0,
        "ambiguous": [],
        "conflicts": [],
        "notes_created": 0,
        "notes_removed": 0,
        "notes_deduped": 0,
        "undated_notes_kept": 0,
        "stripped": 0,
        "archive_repairs": _repair_archive_paths(conn, base, write=write),
        "details": [],
    }
    apps_dir = base / "documents" / "applications"
    outcome_files = sorted(apps_dir.glob("*/outcome.md")) if apps_dir.is_dir() else []
    parsed_by_app: dict[int, dict] = {}
    mapped_dirs: dict[int, str] = {}
    for path in outcome_files:
        report["outcomes"] += 1
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        archive_dir = path.parent.relative_to(base).as_posix()
        parsed = _parse_outcome_text(text)
        if not any(
            (
                parsed["status_raw"],
                parsed["date_resolved"],
                parsed["stages"],
                parsed["dated_notes"],
            )
        ):
            report["details"].append(
                {
                    "file": path.relative_to(base).as_posix(),
                    "application_id": None,
                    "method": "narrative",
                    "dated_notes": 0,
                    "undated_notes": len(parsed["undated_notes"]),
                }
            )
            continue
        app, method = _application_for_outcome(conn, archive_dir, parsed)
        detail = {
            "file": path.relative_to(base).as_posix(),
            "application_id": app.get("id") if app else None,
            "method": method,
            "dated_notes": len(parsed["dated_notes"]),
            "undated_notes": len(parsed["undated_notes"]),
        }
        if app is None:
            report["ambiguous"].append(detail)
            report["details"].append(detail)
            continue
        report["mapped"] += 1
        parsed_by_app[int(app["id"])] = parsed
        mapped_dirs[int(app["id"])] = archive_dir
        app_status = canonical_status(app.get("status"))
        if parsed["status"] and parsed["status"] != "unknown" and parsed["status"] != app_status:
            report["conflicts"].append(
                {
                    "application_id": app.get("id"),
                    "company": app.get("company"),
                    "role": app.get("role"),
                    "field": "status",
                    "database": app_status,
                    "outcome": parsed["status_raw"],
                }
            )
        if parsed["date_resolved"]:
            if not app.get("date_resolved"):
                if write:
                    conn.execute(
                        "UPDATE applications SET date_resolved=?, updated_at=? WHERE id=?",
                        (parsed["date_resolved"], _now(), app.get("id")),
                    )
            elif app.get("date_resolved") != parsed["date_resolved"]:
                report["conflicts"].append(
                    {
                        "application_id": app.get("id"),
                        "company": app.get("company"),
                        "role": app.get("role"),
                        "field": "date_resolved",
                        "database": app.get("date_resolved"),
                        "outcome": parsed["date_resolved"],
                    }
                )
        for stage, when in parsed["stages"]:
            existing = conn.execute(
                "SELECT date FROM application_stages WHERE application_id=? AND stage=?",
                (app.get("id"), stage),
            ).fetchone()
            if existing and existing["date"] and when and existing["date"] != when:
                report["conflicts"].append(
                    {
                        "application_id": app.get("id"),
                        "company": app.get("company"),
                        "role": app.get("role"),
                        "field": f"stage:{stage}",
                        "database": existing["date"],
                        "outcome": when,
                    }
                )
                continue
            if write:
                _set_stage(conn, int(app["id"]), stage, True, when, "legacy-outcome")
        for note in parsed["dated_notes"]:
            existing_notes = [
                row["text"]
                for row in conn.execute(
                    "SELECT text FROM application_events WHERE application_id=? "
                    "AND event_type='note' AND COALESCE(event_date, '')=?",
                    (app.get("id"), note["date"]),
                )
            ]
            duplicate = any(
                _notes_are_duplicates(note["text"], text) for text in existing_notes
            )
            if write and not duplicate:
                created = _insert_event(
                    conn,
                    int(app["id"]),
                    "note",
                    event_date=note["date"],
                    text=note["text"],
                    source="legacy-outcome",
                    metadata={"legacy_path": detail["file"]},
                )
            else:
                created = False if duplicate else True
            if created:
                report["notes_created"] += 1
        report["undated_notes_kept"] += len(parsed["undated_notes"])
        report["details"].append(detail)

    for app in [dict(row) for row in conn.execute("SELECT * FROM applications ORDER BY id")]:
        notes = str(app.get("notes") or "")
        prefix, fragments = _split_dated_notes(notes)
        if not fragments:
            if notes.strip():
                report["undated_notes_kept"] += 1
            continue
        for fragment in fragments:
            existing_notes = [
                row["text"]
                for row in conn.execute(
                    "SELECT text FROM application_events WHERE application_id=? "
                    "AND event_type='note' AND COALESCE(event_date, '')=?",
                    (app.get("id"), fragment["date"]),
                )
            ]
            duplicate = any(
                _notes_are_duplicates(fragment["text"], text) for text in existing_notes
            )
            if write and not duplicate:
                created = _insert_event(
                    conn,
                    int(app["id"]),
                    "note",
                    event_date=fragment["date"],
                    text=fragment["text"],
                    source="legacy-notes",
                    metadata={"legacy_field": "applications.notes"},
                )
            else:
                created = False if duplicate else True
            if created:
                report["notes_created"] += 1
        report["notes_removed"] += len(fragments)
        if write:
            conn.execute(
                "UPDATE applications SET notes=?, updated_at=? WHERE id=?",
                (prefix, _now(), app["id"]),
            )

    dedupe = _dedupe_note_events(conn, write=write)
    report["notes_deduped"] = dedupe["deleted"]
    report["deduped_events"] = dedupe["details"]

    if write and strip_outcome:
        for app_id, parsed in parsed_by_app.items():
            archive_dir = mapped_dirs.get(app_id)
            if not archive_dir:
                continue
            path = base / archive_dir / "outcome.md"
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            cleaned, removed = _strip_outcome_text(text)
            if cleaned != text:
                path.write_text(cleaned, encoding="utf-8")
                report["stripped"] += 1
        report["tidied"] = 0
        for path in outcome_files:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            cleaned = _tidy_outcome_text(text)
            if cleaned != text:
                path.write_text(cleaned, encoding="utf-8")
                report["tidied"] += 1
    if write:
        conn.commit()
    return report

__all__ = [name for name in globals() if not name.startswith("__")]
