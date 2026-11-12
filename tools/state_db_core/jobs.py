"""Job rows, ranking helpers, and job queries."""

from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from fractions import Fraction

from .common import *

# The statuses a /rank scoring agent may return (rank.md Step 2).
AGENT_STATUSES = ("scored", "expired", "unreachable")

# The values the two veto gates may take (rank.md Step 2).
GATE_VERDICTS = ("PASS", "FAIL", "FLAG")

# A posting that could not be fetched is `unreachable`, not `expired`, and is
# retried on later runs (#534). It gives up to `expired` only after this many
# failed attempts with at least this long between the first and the last.
UNREACHABLE_MAX_ATTEMPTS = 3
UNREACHABLE_MIN_SPAN = timedelta(hours=48)
FETCH_ERROR_MAX = 200
RETRY_FIELDS = ("fetch_attempts", "first_unreachable", "last_fetch_error")
TIMESTAMP = "%Y-%m-%dT%H:%M:%SZ"


def _parse_timestamp(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.strptime(value.strip(), TIMESTAMP)
    except ValueError:
        return None
    return parsed.replace(tzinfo=timezone.utc)


def _parse_now(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

def _job_exists(conn: sqlite3.Connection, key: str) -> bool:
    return conn.execute("SELECT 1 FROM jobs WHERE job_key = ?", (key,)).fetchone() is not None


def _job_row(conn: sqlite3.Connection, key: str) -> dict | None:
    row = conn.execute("SELECT * FROM jobs WHERE job_key = ?", (key,)).fetchone()
    return dict(row) if row else None


def _job_payload(entry: dict, key: str | None = None) -> dict:
    data = dict(entry)
    job_key = key or str(data.get("job_key") or data.get("key") or "").strip()
    if not job_key:
        job_key = make_key(
            str(data.get("company") or ""),
            str(data.get("title") or ""),
            str(data.get("url") or ""),
        )
    data["job_key"] = job_key
    return data


def upsert_job(conn: sqlite3.Connection, entry: dict, key: str | None = None) -> dict:
    data = _job_payload(entry, key)
    job_key = data["job_key"]
    existing = _job_row(conn, job_key) or {}
    now = _now()
    location = str(data.get("location") or "")
    location_verdict = str(data.get("location_verdict") or "")
    if location in {"PASS", "FAIL", "FLAG"}:
        location_verdict = location_verdict or location
        location = ""
    known = {
        "job_key", "key", "title", "company", "url", "portal", "source",
        "first_seen", "posted_date", "deadline", "status", "fit",
        "rank_score", "rank_verdict", "rank_date", "location",
        "location_verdict", "language_gate", "language_note",
        "seniority_gate", "seniority_note", "domain_gate", "domain_note",
        "strengths", "gaps", "description_text", "description_hash",
        "description_fetched_at", "language", "fetch_attempts",
        "first_unreachable", "last_fetch_error", "expired_reason", "guard",
    }
    extra = {k: v for k, v in data.items() if k not in known and k not in {"key", "job_key"}}
    if existing.get("extra_json"):
        merged_extra = _load_json(existing["extra_json"], {})
        if isinstance(merged_extra, dict):
            merged_extra.update(extra)
            extra = merged_extra
    description_text = str(data.get("description_text") or existing.get("description_text") or "")
    description_hash = str(data.get("description_hash") or existing.get("description_hash") or "")
    description_changed = description_text != str(existing.get("description_text") or "")
    if description_text and (not description_hash or description_changed):
        description_hash = hashlib.sha256(description_text.encode("utf-8")).hexdigest()
    row = {
        "job_key": job_key,
        "title": str(data.get("title") or existing.get("title") or ""),
        "company": str(data.get("company") or existing.get("company") or ""),
        "company_norm": norm(data.get("company") or existing.get("company")),
        "url": str(data.get("url") or existing.get("url") or ""),
        "url_norm": url_norm(data.get("url") or existing.get("url")),
        "portal": str(data.get("portal") or existing.get("portal") or ""),
        "source": str(data.get("source") or existing.get("source") or ""),
        "first_seen": parse_date(data.get("first_seen")) or existing.get("first_seen"),
        "posted_date": parse_date(data.get("posted_date")) or existing.get("posted_date"),
        "deadline": (
            parse_date(data.get("deadline")) or str(data.get("deadline")).strip()
            if data.get("deadline") not in (None, "")
            else existing.get("deadline")
        ),
        "status": str(data.get("status") or existing.get("status") or "new"),
        "fit": str(data.get("fit") or existing.get("fit") or ""),
        "rank_score": data.get("rank_score", existing.get("rank_score")),
        "rank_verdict": str(data.get("rank_verdict") or existing.get("rank_verdict") or ""),
        "rank_date": parse_date(data.get("rank_date")) or existing.get("rank_date"),
        "location": location or existing.get("location") or "",
        "location_verdict": location_verdict or existing.get("location_verdict") or "",
        "language_gate": str(data.get("language_gate") or existing.get("language_gate") or ""),
        "language_note": str(data.get("language_note") or existing.get("language_note") or ""),
        "seniority_gate": str(data.get("seniority_gate") or existing.get("seniority_gate") or ""),
        "seniority_note": str(data.get("seniority_note") or existing.get("seniority_note") or ""),
        "domain_gate": str(data.get("domain_gate") or existing.get("domain_gate") or ""),
        "domain_note": str(data.get("domain_note") or existing.get("domain_note") or ""),
        "description_text": description_text,
        "description_hash": description_hash,
        "description_fetched_at": (
            str(data.get("description_fetched_at") or "")
            or (_now() if description_changed and description_text else existing.get("description_fetched_at"))
        ),
        "language": str(data.get("language") or existing.get("language") or ""),
        "fetch_attempts": int(data.get("fetch_attempts") or existing.get("fetch_attempts") or 0),
        "first_unreachable": str(data.get("first_unreachable") or existing.get("first_unreachable") or ""),
        "last_fetch_error": str(data.get("last_fetch_error") or existing.get("last_fetch_error") or ""),
        "expired_reason": str(data.get("expired_reason") or existing.get("expired_reason") or ""),
        "guard": str(data.get("guard") or existing.get("guard") or ""),
        "strengths_json": json.dumps(data.get("strengths", existing.get("strengths", [])), ensure_ascii=False),
        "gaps_json": json.dumps(data.get("gaps", existing.get("gaps", [])), ensure_ascii=False),
        "extra_json": json.dumps(extra, ensure_ascii=False),
        "created_at": existing.get("created_at") or now,
        "updated_at": now,
    }
    columns = list(row)
    conn.execute(
        f"INSERT INTO jobs ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)}) "
        f"ON CONFLICT(job_key) DO UPDATE SET "
        + ", ".join(f"{column}=excluded.{column}" for column in columns if column != "job_key"),
        [row[column] for column in columns],
    )
    return _job_row(conn, job_key) or row


def _backfill_job_match(conn: sqlite3.Connection, app: dict) -> tuple[dict | None, str, list[dict]]:
    job_key = str(app.get("job_key") or "").strip()
    if job_key:
        row = _job_row(conn, job_key)
        if row:
            return row, "job_key", []
    source = str(app.get("source_url") or "").strip()
    normalized_url = url_norm(source)
    if normalized_url:
        rows = [
            dict(row)
            for row in conn.execute("SELECT * FROM jobs WHERE url_norm = ?", (normalized_url,))
        ]
        if len(rows) == 1:
            return rows[0], "url", []
        if len(rows) > 1:
            return None, "ambiguous", rows
    company_norm = str(app.get("company_norm") or "") or norm(app.get("company"))
    role_norm = str(app.get("role_norm") or "") or norm(app.get("role"))
    if company_norm and role_norm:
        rows = [
            dict(row)
            for row in conn.execute("SELECT * FROM jobs WHERE company_norm = ?", (company_norm,))
        ]
        matches = [row for row in rows if norm(row.get("title")) == role_norm]
        if len(matches) == 1:
            return matches[0], "company_title", []
        if len(matches) > 1:
            return None, "ambiguous", matches
    return None, "unmatched", []


def backfill_job_descriptions(
    conn: sqlite3.Connection,
    repo: Path | str | None = None,
    *,
    write: bool = False,
    replace: bool = False,
    limit: int = 0,
) -> dict:
    """Fill jobs.description_* from archived job_posting.md files.

    Dry-run by default. Matching is exact in this order: job_key, normalized
    URL, then normalized company+title. A fallback match must be unique.
    """
    base = Path(repo) if repo else ROOT
    rows = [
        dict(row)
        for row in conn.execute(
            "SELECT id, job_key, source_url, company, company_norm, role, role_norm, archive_path "
            "FROM applications WHERE archive_path <> '' ORDER BY id"
        )
    ]
    if limit and limit > 0:
        rows = rows[:limit]
    report = {
        "mode": "write" if write else "dry-run",
        "scanned": 0,
        "matched": 0,
        "updated": 0,
        "would_update": 0,
        "unchanged": 0,
        "skipped_existing": 0,
        "ambiguous": 0,
        "unmatched": 0,
        "missing_posting": 0,
        "identity_mismatch": 0,
        "errors": 0,
        "details": [],
    }
    for app in rows:
        report["scanned"] += 1
        detail = {
            "application_id": app.get("id"),
            "job_key": app.get("job_key") or "",
            "posting": "",
            "match": "",
            "action": "",
        }
        archive_dir = Path(str(app.get("archive_path") or ""))
        if not archive_dir.is_absolute():
            archive_dir = base / archive_dir
        posting_path = archive_dir / "job_posting.md"
        detail["posting"] = posting_path.as_posix()
        if not posting_path.is_file():
            report["missing_posting"] += 1
            detail["action"] = "missing_posting"
            report["details"].append(detail)
            continue
        try:
            text = posting_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            report["errors"] += 1
            detail.update(action="error", error=str(exc))
            report["details"].append(detail)
            continue
        if not text.strip():
            report["errors"] += 1
            detail.update(action="error", error="empty posting")
            report["details"].append(detail)
            continue
        expected_id = _app_vacancy_id(app) or hh_vacancy_id(app.get("source_url"))
        posting_ids = _posting_vacancy_ids(text)
        if expected_id and posting_ids and expected_id not in posting_ids:
            report.setdefault("identity_mismatch", 0)
            report["identity_mismatch"] += 1
            detail.update(action="identity_mismatch", expected_id=expected_id)
            report["details"].append(detail)
            continue
        job, method, candidates = _backfill_job_match(conn, app)
        detail["match"] = method
        if job is None:
            key = "ambiguous" if method == "ambiguous" else "unmatched"
            report[key] += 1
            detail["action"] = method
            if candidates:
                detail["candidates"] = [candidate.get("job_key") for candidate in candidates]
            report["details"].append(detail)
            continue
        report["matched"] += 1
        detail["job_key"] = job["job_key"]
        current_text = str(job.get("description_text") or "")
        current_hash = str(job.get("description_hash") or "")
        new_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if not current_text:
            action = "updated"
        elif current_hash == new_hash:
            action = "unchanged"
        elif not replace:
            action = "skipped_existing"
        else:
            action = "updated"
        if action == "updated" and write:
            try:
                fetched_at = datetime.fromtimestamp(
                    posting_path.stat().st_mtime, tz=timezone.utc
                ).isoformat(timespec="seconds")
            except OSError:
                fetched_at = None
            conn.execute(
                "UPDATE jobs SET description_text=?, description_hash=?, "
                "description_fetched_at=?, language=? WHERE job_key=?",
                (text, new_hash, fetched_at, detect_language(text), job["job_key"]),
            )
        if action == "updated":
            if write:
                report["updated"] += 1
            else:
                report["would_update"] += 1
        elif action == "unchanged":
            report["unchanged"] += 1
        else:
            report["skipped_existing"] += 1
        detail["action"] = action if write or action != "updated" else "would_update"
        report["details"].append(detail)
    if write:
        conn.commit()
    return report


OUTCOME_DATE_NOTE_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})\s*[:—–-]\s*(?P<text>.+)$"
)
OUTCOME_STAGE_RE = re.compile(
    r"^-\s*\[[xX]\]\s*([^\n(]+?)(?:\s*\((\d{4}-\d{2}-\d{2})\))?\s*$",
    re.MULTILINE,
)
POSTING_URL_RE = re.compile(r"https?://[^\s)>\]\"']+")

def _set_job_description(
    conn: sqlite3.Connection,
    job: dict,
    text: str,
    posting_path: Path,
    *,
    replace: bool,
) -> bool:
    if not text.strip():
        return False
    current = str(job.get("description_text") or "")
    if current and not replace:
        return False
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if current and hashlib.sha256(current.encode("utf-8")).hexdigest() == digest:
        return False
    try:
        fetched_at = datetime.fromtimestamp(
            posting_path.stat().st_mtime, tz=timezone.utc
        ).isoformat(timespec="seconds")
    except OSError:
        fetched_at = _now()
    conn.execute(
        "UPDATE jobs SET description_text=?, description_hash=?, "
        "description_fetched_at=?, language=?, updated_at=? WHERE job_key=?",
        (text, digest, fetched_at, detect_language(text), _now(), job["job_key"]),
    )
    return True

def _overall_score(scores: dict) -> int:
    if not isinstance(scores, dict):
        raise ValueError("scores must be an object")
    total = Fraction(0)
    for dimension, weight in WEIGHTS.items():
        value = scores.get(dimension)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"missing or non-numeric score '{dimension}'")
        if not 0 <= value <= 100:
            raise ValueError(f"score '{dimension}' must be between 0 and 100")
        # Decimal weights and scores: binary float summation can turn 59.5
        # into 59.49999999999999 and drop a valid result into the lower band.
        total += Fraction(str(value)) * Fraction(str(weight))
    return int(total + Fraction(1, 2))


def _band(score: int) -> str:
    for floor, name in BANDS:
        if score >= floor:
            return name
    return "Poor Fit"


def job_candidates(conn: sqlite3.Connection, *, show_all: bool = False, focus: str = "", limit: int = 10) -> dict:
    applications = conn.execute("SELECT company_norm, role_norm FROM applications").fetchall()
    excluded = {(row["company_norm"], row["role_norm"]) for row in applications}
    selected = []
    skipped_tracker = 0
    rows = conn.execute("SELECT * FROM jobs ORDER BY first_seen, job_key").fetchall()
    for row in rows:
        entry = dict(row)
        status = str(entry.get("status") or "")
        if not show_all and status not in ("new", "unreachable"):
            continue
        if show_all and status in {"skipped", "archived"}:
            continue
        if (entry.get("company_norm"), norm(entry.get("title"))) in excluded:
            skipped_tracker += 1
            continue
        if focus:
            haystack = " ".join(
                [str(entry.get("title") or ""), str(entry.get("company") or "")]
                + [str(item) for item in _load_json(entry.get("strengths_json"), [])]
                + [str(item) for item in _load_json(entry.get("gaps_json"), [])]
            ).casefold()
            if focus.casefold() not in haystack:
                continue
        selected.append(
            {
                "key": entry["job_key"],
                "title": entry.get("title"),
                "company": entry.get("company"),
                "url": entry.get("url"),
                "portal": entry.get("portal"),
                "deadline": entry.get("deadline"),
                "posted_date": entry.get("posted_date"),
            }
        )
    eligible = len(selected)
    if limit > 0:
        selected = selected[:limit]
    return {
        "eligible": eligible,
        "selected": selected,
        "deferred": max(0, eligible - len(selected)),
        "excluded_by_tracker": skipped_tracker,
        "total_entries": conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0],
    }

def job_context(conn: sqlite3.Connection) -> dict:
    urls = []
    company_titles = []
    for row in conn.execute("SELECT job_key, url, url_norm, company_norm, title FROM jobs"):
        if row["url"]:
            urls.append(row["url"])
        company_titles.append([row["company_norm"], norm(row["title"]), row["job_key"]])
    tracked = [
        [row["company_norm"], row["role_norm"]]
        for row in conn.execute("SELECT company_norm, role_norm FROM applications")
    ]
    return {"urls": urls, "company_titles": company_titles, "tracked": tracked}


def job_exists(conn: sqlite3.Connection, *, url: str = "", company: str = "", title: str = "") -> dict | None:
    normalized = url_norm(url)
    if normalized:
        row = conn.execute("SELECT * FROM jobs WHERE url_norm = ?", (normalized,)).fetchone()
        if row:
            return dict(row)
    company_norm = norm(company)
    title_norm = norm(title)
    if company_norm and title_norm:
        for row in conn.execute(
            "SELECT * FROM jobs WHERE company_norm = ? ORDER BY first_seen DESC",
            (company_norm,),
        ):
            if norm(row["title"]) == title_norm:
                return dict(row)
    return None


def job_sweep(conn: sqlite3.Connection, *, write: bool = False, exclude: set[str] | None = None, today: str | None = None) -> dict:
    # "a_b, c_d" is as natural a comma-separated list as "a_b,c_d"; keys never
    # carry surrounding whitespace, so a space must not un-exclude a key.
    exclude = {str(item).strip() for item in (exclude or set()) if str(item).strip()}
    today_date = date.fromisoformat(parse_date(today or _today()) or _today())
    expired, closing, unparseable = [], [], []
    checked = 0
    rows = conn.execute("SELECT * FROM jobs WHERE status = 'ranked'").fetchall()
    for row in rows:
        entry = dict(row)
        key = entry["job_key"]
        if exclude and key in exclude:
            continue
        checked += 1
        raw = entry.get("deadline")
        if raw in (None, ""):
            continue
        parsed = parse_date(raw)
        if parsed is None:
            unparseable.append({"key": key, "portal": entry.get("portal"), "deadline": raw})
            continue
        parsed_date = date.fromisoformat(parsed)
        item = {"key": key, "title": entry.get("title"), "company": entry.get("company"), "url": entry.get("url"), "deadline": raw}
        if parsed_date < today_date:
            expired.append(item)
        elif (parsed_date - today_date).days <= URGENT_DAYS:
            closing.append(item)
    if write and expired:
        for item in expired:
            conn.execute("UPDATE jobs SET status='expired', updated_at=? WHERE job_key=?", (_now(), item["key"]))
        conn.commit()
    return {
        "swept": checked,
        "newly_expired": expired,
        "closing_soon": sorted(closing, key=lambda item: item["deadline"]),
        "unparseable_deadlines": unparseable,
        "written": bool(write and expired),
    }


def _apply_job_updates(conn: sqlite3.Connection, key: str, updates: dict, dry_run: bool) -> None:
    if dry_run or not updates:
        return
    updates = dict(updates)
    updates["updated_at"] = _now()
    conn.execute(
        "UPDATE jobs SET " + ", ".join(f"{column}=?" for column in updates) + " WHERE job_key=?",
        [*updates.values(), key],
    )


def _clear_retry(updates: dict) -> None:
    updates["fetch_attempts"] = 0
    updates["first_unreachable"] = ""
    updates["last_fetch_error"] = ""
    updates["expired_reason"] = ""


def job_apply_rank(
    conn: sqlite3.Connection,
    results: list[dict],
    *,
    today: str | None = None,
    now: str | None = None,
    dry_run: bool = False,
) -> dict:
    today_value = parse_date(today or _today()) or _today()
    today_date = date.fromisoformat(today_value)
    now_dt = _parse_now(now)
    rows, expired, unreachable, gave_up, errors = [], [], [], [], []
    for result in results:
        if not isinstance(result, dict):
            errors.append({"key": None, "error": "result is not an object"})
            continue
        key = str(result.get("key") or "").strip()
        entry = _job_row(conn, key) if key else None
        if entry is None:
            errors.append({"key": key, "error": "no such job key"})
            continue

        # A missing status is a score, as it always was; a misspelt one is an
        # error rather than a fall-through that reports a "missing score".
        status = result.get("status", "scored")
        if status not in AGENT_STATUSES:
            errors.append(
                {"key": key, "error": f"unknown status {status!r}; expected one of {', '.join(AGENT_STATUSES)}"}
            )
            continue

        if status == "unreachable":
            # A stored deadline that has already passed is positive evidence the
            # posting is closed, whatever the fetch did: expire it instead of
            # retrying it and later listing it as possibly live.
            stored_deadline = parse_date(entry.get("deadline"))
            if stored_deadline and date.fromisoformat(stored_deadline) < today_date:
                updates = {"status": "expired"}
                _clear_retry(updates)
                _apply_job_updates(conn, key, updates, dry_run)
                expired.append(
                    {"key": key, "title": entry.get("title"), "company": entry.get("company"), "url": entry.get("url")}
                )
                continue

            previous = entry.get("fetch_attempts")
            valid = isinstance(previous, int) and not isinstance(previous, bool)
            attempts = (previous if valid else 0) + 1
            first = _parse_timestamp(entry.get("first_unreachable")) or now_dt
            # Plain, bounded text: it is shown in the report, never acted on.
            error = " ".join(str(result.get("fetch_error") or "").split())[:FETCH_ERROR_MAX]
            updates = {
                "status": "unreachable",
                "fetch_attempts": attempts,
                "first_unreachable": first.strftime(TIMESTAMP),
            }
            if error:
                updates["last_fetch_error"] = error
            row = {
                "key": key,
                "title": entry.get("title"),
                "company": entry.get("company"),
                "url": entry.get("url"),
                "fetch_attempts": attempts,
                "last_fetch_error": updates.get("last_fetch_error", entry.get("last_fetch_error")),
            }
            if attempts >= UNREACHABLE_MAX_ATTEMPTS and now_dt - first >= UNREACHABLE_MIN_SPAN:
                # The retry fields stay on the entry as its history; `--all`
                # can still revive it, like any other expired entry.
                updates["status"] = "expired"
                updates["expired_reason"] = "unreachable"
                gave_up.append(row)
            else:
                unreachable.append(row)
            _apply_job_updates(conn, key, updates, dry_run)
            continue

        if status == "expired":
            updates = {"status": "expired"}
            _clear_retry(updates)
            _apply_job_updates(conn, key, updates, dry_run)
            expired.append(
                {"key": key, "title": entry.get("title"), "company": entry.get("company"), "url": entry.get("url")}
            )
            continue

        try:
            score = _overall_score(result.get("scores") or {})
        except ValueError as exc:
            errors.append({"key": key, "error": str(exc)})
            continue

        bad_gate = next(
            (
                field
                for field in ("location_verdict", "language_gate", "seniority_gate", "domain_gate")
                if result.get(field) and result[field] not in GATE_VERDICTS
            ),
            None,
        )
        if bad_gate:
            errors.append(
                {"key": key, "error": f"unknown {bad_gate} {result[bad_gate]!r}; expected one of {', '.join(GATE_VERDICTS)}"}
            )
            continue

        # A missing deadline from the fresh fetch is not a correction to the
        # stored date. Scored keys are excluded from the later sweep, so apply
        # must retire a passed deadline before updating any ranking metadata.
        parsed = parse_date(result.get("deadline") or entry.get("deadline"))
        if parsed is not None and date.fromisoformat(parsed) < today_date:
            updates = {"status": "expired"}
            _clear_retry(updates)
            if result.get("deadline"):
                updates["deadline"] = parsed
            _apply_job_updates(conn, key, updates, dry_run)
            expired.append(
                {"key": key, "title": entry.get("title"), "company": entry.get("company"), "url": entry.get("url")}
            )
            continue

        legacy_verdict = entry.get("location_verdict") if entry.get("location_verdict") in GATE_VERDICTS else None
        updates = {
            "status": "ranked",
            "rank_score": score,
            "rank_verdict": _band(score),
            "rank_date": today_value,
            "location_verdict": result.get("location_verdict") or legacy_verdict or "PASS",
            "language_gate": result.get("language_gate") or "PASS",
            "language_note": "" if (result.get("language_gate") or "PASS") == "PASS" else str(result.get("language_note") or ""),
            "seniority_gate": result.get("seniority_gate") or "PASS",
            "seniority_note": "" if (result.get("seniority_gate") or "PASS") == "PASS" else str(result.get("seniority_note") or ""),
            "domain_gate": result.get("domain_gate") or "PASS",
            "domain_note": "" if (result.get("domain_gate") or "PASS") == "PASS" else str(result.get("domain_note") or ""),
        }
        _clear_retry(updates)
        if result.get("deadline"):
            updates["deadline"] = parse_date(result["deadline"]) or entry.get("deadline")
        for field, column in (("strengths", "strengths_json"), ("gaps", "gaps_json")):
            value = result.get(field)
            if isinstance(value, list):
                updates[column] = json.dumps([str(item) for item in value][:3], ensure_ascii=False)

        # The scoring agent's posting_guard verdict line ("clean" or the warning
        # line). Normalised so Step 5's "anything other than clean" rule holds;
        # a rescoring result without a guard drops a stale one.
        guard = result.get("guard")
        if isinstance(guard, str) and guard.strip():
            text = guard.strip()
            if text.lower().startswith("posting_guard:"):
                text = text[len("posting_guard:"):].strip()
            updates["guard"] = "clean" if text.lower().startswith("clean") else text[:200]
        else:
            updates["guard"] = ""

        _apply_job_updates(conn, key, updates, dry_run)
        parsed = parse_date(updates.get("deadline") or entry.get("deadline"))
        rows.append(
            {
                "key": key,
                "title": entry.get("title"),
                "company": entry.get("company"),
                "location": entry.get("location"),
                "url": entry.get("url"),
                "score": score,
                "verdict": updates["rank_verdict"],
                "location_verdict": updates["location_verdict"],
                "language_gate": updates["language_gate"],
                "language_note": updates["language_note"],
                "seniority_gate": updates["seniority_gate"],
                "seniority_note": updates["seniority_note"],
                "domain_gate": updates["domain_gate"],
                "domain_note": updates["domain_note"],
                "deadline": updates.get("deadline") or entry.get("deadline"),
                "posted_date": entry.get("posted_date"),
                "urgent": bool(parsed and today_date <= date.fromisoformat(parsed) <= today_date + timedelta(days=URGENT_DAYS)),
                "strengths": _load_json(updates.get("strengths_json") or entry.get("strengths_json"), []),
                "gaps": _load_json(updates.get("gaps_json") or entry.get("gaps_json"), []),
                "guard": updates.get("guard") or None,
            }
        )
    if not dry_run:
        conn.commit()
    rows.sort(key=lambda item: (item["score"], item["urgent"]), reverse=True)
    veto = lambda item: (
        item["location_verdict"] == "FAIL"
        or item["language_gate"] == "FAIL"
        or item["seniority_gate"] == "FAIL"
        or item["domain_gate"] == "FAIL"
    )
    return {
        "ranked": [item for item in rows if not veto(item)],
        "vetoed": [item for item in rows if veto(item)],
        "expired": expired,
        "unreachable": unreachable,
        "gave_up": gave_up,
        "errors": errors,
        "written": not dry_run,
    }


def dump_jobs(conn: sqlite3.Connection) -> dict:
    result = {}
    for row in conn.execute("SELECT * FROM jobs ORDER BY job_key"):
        entry = dict(row)
        data = {
            "title": entry.get("title"),
            "company": entry.get("company"),
            "url": entry.get("url"),
            "first_seen": entry.get("first_seen"),
            "posted_date": entry.get("posted_date"),
            "deadline": entry.get("deadline"),
            "fit": entry.get("fit"),
            "status": entry.get("status"),
            "portal": entry.get("portal"),
            "source": entry.get("source"),
            "rank_score": entry.get("rank_score"),
            "rank_verdict": entry.get("rank_verdict"),
            "rank_date": entry.get("rank_date"),
            "strengths": _load_json(entry.get("strengths_json"), []),
            "gaps": _load_json(entry.get("gaps_json"), []),
        }
        for key in ("location", "location_verdict", "language_gate", "language_note", "seniority_gate", "seniority_note", "domain_gate", "domain_note"):
            if entry.get(key):
                data[key] = entry[key]
        extra = _load_json(entry.get("extra_json"), {})
        if isinstance(extra, dict):
            data.update(extra)
        result[entry["job_key"]] = data
    return {"seen": result}

__all__ = [name for name in globals() if not name.startswith("__")]
