"""Funnel metrics, markdown reports, and upskill data."""

from __future__ import annotations

import json
import math
from datetime import date, timedelta

from .common import *
from .applications import _application_payload

def upskill_data(conn: sqlite3.Connection) -> dict:
    applications = []
    for row in conn.execute(
        "SELECT * FROM applications WHERE status NOT IN ('drafted', 'unknown') "
        "ORDER BY COALESCE(applied_on, created_at) DESC"
    ):
        app = dict(row)
        events = [
            dict(event)
            for event in conn.execute(
                "SELECT event_date, event_type, text FROM application_events "
                "WHERE application_id=? AND event_type='note' ORDER BY event_date, id",
                (app.get("id"),),
            )
        ]
        applications.append(
            {
                "company": app.get("company"),
                "role": app.get("role"),
                "sector": app.get("sector"),
                "role_type": app.get("role_type"),
                "fit_rating": app.get("fit_rating"),
                "notes": app.get("notes"),
                "event_notes": events,
                "status": app.get("status"),
            }
        )
    ranked = []
    for row in conn.execute(
        "SELECT * FROM jobs WHERE status = 'ranked' AND rank_score >= 45 "
        "ORDER BY rank_score DESC, first_seen DESC"
    ):
        job = dict(row)
        ranked.append(
            {
                "key": job.get("job_key"),
                "title": job.get("title"),
                "company": job.get("company"),
                "rank_score": job.get("rank_score"),
                "gaps": _load_json(job.get("gaps_json"), []),
                "strengths": _load_json(job.get("strengths_json"), []),
            }
        )
    return {"applications": applications, "ranked": ranked}

def _wilson(successes: int, total: int) -> tuple[float, float] | None:
    if total <= 0:
        return None
    z = 1.96
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denominator
    return max(0.0, center - margin), min(1.0, center + margin)


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def _rate(successes: int, total: int) -> dict:
    interval = _wilson(successes, total)
    return {
        "n": total,
        "successes": successes,
        "rate": successes / total if total else None,
        "ci_low": interval[0] if interval else None,
        "ci_high": interval[1] if interval else None,
    }


def _fetch_applications(conn: sqlite3.Connection) -> list[dict]:
    rows = [dict(row) for row in conn.execute("SELECT * FROM applications ORDER BY COALESCE(applied_on, created_at), id")]
    result = []
    for row in rows:
        result.append(_application_payload(conn, row))
    return result


def _is_response(row: dict) -> bool:
    return canonical_status(row.get("status")) in {"rejected", "interview", "offer", "hired", "offer_declined", "interview_only"}


def _is_resolved(row: dict) -> bool:
    return canonical_status(row.get("status")) in FINAL_STATUSES


def _is_submitted(row: dict) -> bool:
    return canonical_status(row.get("status")) not in {"drafted", "unknown"}


def _reached_interview(row: dict) -> bool:
    status = canonical_status(row.get("status"))
    if status in {"interview", "offer", "hired", "interview_only"}:
        return True
    return any(stage.get("reached") and stage.get("stage") in STAGES for stage in row.get("stages", []))


def _reached_offer(row: dict) -> bool:
    status = canonical_status(row.get("status"))
    if status in {"offer", "hired"}:
        return True
    return any(stage.get("reached") and stage.get("stage") == "offer" for stage in row.get("stages", []))


def _week_start(value: str | None) -> str:
    parsed = parse_date(value)
    if not parsed:
        return "unknown"
    day = date.fromisoformat(parsed)
    return (day - timedelta(days=day.weekday())).isoformat()


def compute_stats(conn: sqlite3.Connection) -> dict:
    rows = _fetch_applications(conn)
    submitted = [row for row in rows if _is_submitted(row)]
    resolved = [row for row in submitted if _is_resolved(row)]
    status_counts: dict[str, int] = {}
    for row in rows:
        status = canonical_status(row.get("status"))
        status_counts[status] = status_counts.get(status, 0) + 1
    interviews = [row for row in submitted if _reached_interview(row)]
    offers = [row for row in submitted if _reached_offer(row)]
    rejected = [row for row in submitted if canonical_status(row.get("status")) == "rejected"]
    no_response = [row for row in submitted if canonical_status(row.get("status")) == "no_response"]
    responses = [row for row in submitted if _is_response(row)]
    funnel = {
        "submitted": len(submitted),
        "response": _rate(len(responses), len(submitted)),
        "interview": _rate(len(interviews), len(submitted)),
        "offer": _rate(len(offers), len(submitted)),
        "rejection": _rate(len(rejected), len(resolved)),
        "no_response": _rate(len(no_response), len(resolved)),
    }
    cover_groups: dict[str, list[dict]] = {}
    for row in submitted:
        value = canonical_cover_letter(row.get("cover_letter_used"))
        cover_groups.setdefault(value, []).append(row)
    cover = {}
    for value in ("used", "not_used", "not_required", "unknown"):
        group = cover_groups.get(value, [])
        cover[value] = {
            "n": len(group),
            "response": _rate(sum(1 for row in group if _is_response(row)), len(group)),
            "interview": _rate(sum(1 for row in group if _reached_interview(row)), len(group)),
        }
    fit_buckets: dict[str, list[dict]] = {}
    for row in submitted:
        fit = row.get("fit_rating")
        if fit is None:
            bucket = "unknown"
        elif fit >= 75:
            bucket = "strong"
        elif fit >= 60:
            bucket = "good"
        elif fit >= 45:
            bucket = "moderate"
        elif fit >= 30:
            bucket = "weak"
        else:
            bucket = "poor"
        fit_buckets.setdefault(bucket, []).append(row)
    fit = {
        bucket: {
            "n": len(group),
            "interview": _rate(sum(1 for row in group if _reached_interview(row)), len(group)),
        }
        for bucket, group in fit_buckets.items()
    }
    weekly: dict[str, dict] = {}
    for row in submitted:
        week = _week_start(row.get("applied_on"))
        bucket = weekly.setdefault(week, {"week": week, "applications": 0, "interviews": 0, "offers": 0, "rejected": 0, "no_response": 0, "open": 0})
        bucket["applications"] += 1
        bucket["interviews"] += 1 if _reached_interview(row) else 0
        bucket["offers"] += 1 if _reached_offer(row) else 0
        bucket["rejected"] += 1 if canonical_status(row.get("status")) == "rejected" else 0
        bucket["no_response"] += 1 if canonical_status(row.get("status")) == "no_response" else 0
        bucket["open"] += 1 if not _is_resolved(row) else 0
    timing = []
    for row in submitted:
        applied = parse_date(row.get("applied_on"))
        response_date = parse_date(row.get("first_response_date")) or parse_date(row.get("date_resolved"))
        if applied and response_date:
            try:
                timing.append((date.fromisoformat(response_date) - date.fromisoformat(applied)).days)
            except ValueError:
                pass
    timing.sort()
    median = timing[len(timing) // 2] if timing else None
    cover_unknown = sum(1 for row in submitted if canonical_cover_letter(row.get("cover_letter_used")) == "unknown")
    cv_unknown = sum(1 for row in submitted if row.get("cv_version_id") is None)
    fit_unknown = sum(1 for row in submitted if row.get("fit_rating") is None)
    response_unknown = sum(1 for row in submitted if not row.get("first_response_date") and not row.get("date_resolved"))
    return {
        "applications": {
            "total": len(rows),
            "submitted": len(submitted),
            "drafted": sum(1 for row in rows if canonical_status(row.get("status")) == "drafted"),
            "unknown": sum(1 for row in rows if canonical_status(row.get("status")) == "unknown"),
            "resolved": len(resolved),
            "open": sum(1 for row in submitted if not _is_resolved(row)),
            "status_counts": status_counts,
        },
        "funnel": funnel,
        "cover_letter": cover,
        "fit": fit,
        "weekly": sorted(weekly.values(), key=lambda item: item["week"]),
        "timing": {
            "n": len(timing),
            "median_days": median,
            "same_day": sum(1 for days in timing if days == 0),
            "next_day": sum(1 for days in timing if days == 1),
            "within_3_days": sum(1 for days in timing if 0 <= days <= 3),
        },
        "quality": {
            "cover_letter_unknown": cover_unknown,
            "cv_version_unknown": cv_unknown,
            "fit_unknown": fit_unknown,
            "first_response_unknown": response_unknown,
            "submitted": len(submitted),
        },
    }


def _md_table(headers: list[str], rows: list[list[object]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(str(cell) for cell in row) + " |")
    return "\n".join(lines)


def _ci_text(rate: dict) -> str:
    if rate.get("rate") is None:
        return "—"
    return f"{_pct(rate['rate'])} ({_pct(rate['ci_low'])}–{_pct(rate['ci_high'])})"


def stats_markdown(stats: dict) -> str:
    lines = ["# Weekly review", "", f"Data as of: {_now()}", ""]
    applications = stats["applications"]
    lines.append("## Data coverage")
    lines.append(
        _md_table(
            ["Metric", "Value"],
            [
                ["Submitted", applications["submitted"]],
                ["Drafts", applications["drafted"]],
                ["Unknown status", applications["unknown"]],
                ["Resolved", applications["resolved"]],
                ["Open", applications["open"]],
            ],
        )
    )
    lines.append("")
    lines.append("## Funnel")
    funnel = stats["funnel"]
    lines.append(
        _md_table(
            ["Stage", "n", "Rate (95% CI)"],
            [
                ["Submitted", funnel["submitted"], "—"],
                ["Response", funnel["response"]["n"], _ci_text(funnel["response"])],
                ["Interview", funnel["interview"]["n"], _ci_text(funnel["interview"])],
                ["Offer", funnel["offer"]["n"], _ci_text(funnel["offer"])],
                ["Rejected (of resolved)", funnel["rejection"]["n"], _ci_text(funnel["rejection"])],
                ["No response (of resolved)", funnel["no_response"]["n"], _ci_text(funnel["no_response"])],
            ],
        )
    )
    lines.append("")
    lines.append("## Cover letter")
    cover_rows = []
    for value, label in (("used", "Used"), ("not_used", "Not used"), ("not_required", "Not required"), ("unknown", "Unknown")):
        item = stats["cover_letter"][value]
        cover_rows.append([label, item["n"], _ci_text(item["response"]), _ci_text(item["interview"])])
    lines.append(_md_table(["Cover letter", "n", "Response rate", "Interview rate"], cover_rows))
    lines.append("")
    lines.append("## Fit calibration")
    fit_rows = []
    for bucket in ("strong", "good", "moderate", "weak", "poor", "unknown"):
        item = stats["fit"].get(bucket)
        if item:
            fit_rows.append([bucket, item["n"], _ci_text(item["interview"])])
    lines.append(_md_table(["Fit bucket", "n", "Interview rate"], fit_rows))
    lines.append("")
    lines.append("## Weekly activity")
    weekly_rows = [
        [item["week"], item["applications"], item["interviews"], item["offers"], item["rejected"], item["no_response"], item["open"]]
        for item in stats["weekly"][-8:]
    ]
    lines.append(_md_table(["Week", "Applied", "Interview", "Offer", "Rejected", "No response", "Open"], weekly_rows))
    lines.append("")
    lines.append("## Timing")
    timing = stats["timing"]
    lines.append(
        _md_table(
            ["Metric", "Value"],
            [
                ["Applications with response date", timing["n"]],
                ["Median days to first response", timing["median_days"] if timing["median_days"] is not None else "—"],
                ["Same day", timing["same_day"]],
                ["Next day", timing["next_day"]],
                ["Within 3 days", timing["within_3_days"]],
            ],
        )
    )
    lines.append("")
    lines.append("## Data quality")
    quality = stats["quality"]
    lines.append(
        _md_table(
            ["Missing / unknown", "n"],
            [
                ["Cover letter usage", quality["cover_letter_unknown"]],
                ["CV version", quality["cv_version_unknown"]],
                ["Fit rating", quality["fit_unknown"]],
                ["First response date", quality["first_response_unknown"]],
            ],
        )
    )
    return "\n".join(lines) + "\n"


def record_report(conn: sqlite3.Connection, *, report_date: str, period_start: str, period_end: str, metrics: dict, report_path: str) -> int:
    cursor = conn.execute(
        "INSERT INTO report_runs (report_date, period_start, period_end, metrics_json, report_path, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (report_date, period_start, period_end, json.dumps(metrics, ensure_ascii=False), report_path, _now()),
    )
    conn.commit()
    return int(cursor.lastrowid)

__all__ = [name for name in globals() if not name.startswith("__")]
