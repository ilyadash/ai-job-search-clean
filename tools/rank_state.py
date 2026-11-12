#!/usr/bin/env python3
"""State helper for /rank, backed by the SQLite state database.

The CLI keeps the historical `candidates`, `sweep`, and `apply` subcommands.
Without `--state`, it operates on `state/job_search.sqlite`. The optional
`--state <seen_jobs.json>` path is a test/import adapter: it seeds an
in-memory database from a legacy JSON file and writes the results back in the
same shape, but the active workflows never pass it.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import state_db

ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / "job_scraper" / "seen_jobs.json"
TRACKER = ROOT / "job_search_tracker.csv"

WEIGHTS = state_db.WEIGHTS
BANDS = state_db.BANDS
DEFAULT_LIMIT = 10
URGENT_DAYS = state_db.URGENT_DAYS

# Re-exported so tests and the spec can assert the contract in one place.
AGENT_STATUSES = state_db.AGENT_STATUSES
GATE_VERDICTS = state_db.GATE_VERDICTS
UNREACHABLE_MAX_ATTEMPTS = state_db.UNREACHABLE_MAX_ATTEMPTS
UNREACHABLE_MIN_SPAN = state_db.UNREACHABLE_MIN_SPAN
RETRY_FIELDS = state_db.RETRY_FIELDS


def overall_score(scores: dict) -> int:
    return state_db._overall_score(scores)


def band(score: int) -> str:
    return state_db._band(score)


def _load_json_state(path: Path) -> dict:
    if not path.is_file():
        raise state_db.StateError(f"{path} not found - run /scrape first")
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise state_db.StateError(f"{path} is not valid JSON: {exc}") from None
    seen = doc.get("seen") if isinstance(doc, dict) and "seen" in doc else doc
    if not isinstance(seen, dict):
        raise state_db.StateError(f"{path}: expected an object of job entries")
    return seen


def _legacy_conn(seen_path: Path, tracker_path: Path | None) -> sqlite3.Connection:
    seen = _load_json_state(seen_path)
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    state_db.init_connection(conn)
    state_db.seed_legacy(conn, seen, tracker_path)
    return conn


def _open_conn(args) -> tuple[sqlite3.Connection, Path | None]:
    if args.state:
        return _legacy_conn(args.state, args.tracker), args.state
    path = args.db or state_db.db_path()
    state_db.init_db(path.parent.parent)
    return state_db.connect(path), None


def _write_legacy(path: Path, conn: sqlite3.Connection) -> None:
    doc = json.loads(path.read_text(encoding="utf-8"))
    seen = doc.get("seen")
    if not isinstance(seen, dict):
        return
    for key, original in seen.items():
        if not isinstance(original, dict):
            continue
        row = state_db._job_row(conn, str(key))
        if row is None:
            continue
        updated = dict(original)
        for field in (
            "title", "company", "url", "portal", "source", "first_seen",
            "posted_date", "deadline", "fit", "status", "rank_score",
            "rank_verdict", "rank_date", "location", "location_verdict",
            "language_gate", "language_note", "seniority_gate",
            "seniority_note", "domain_gate", "domain_note",
        ):
            value = row.get(field)
            if value not in (None, ""):
                updated[field] = value
        for field in ("fetch_attempts", "first_unreachable", "last_fetch_error", "expired_reason", "guard"):
            value = row.get(field)
            if value:
                updated[field] = value
            else:
                updated.pop(field, None)
        for field, column in (("strengths", "strengths_json"), ("gaps", "gaps_json")):
            value = state_db._load_json(row.get(column), [])
            if value:
                updated[field] = value
        if row.get("location_verdict") and not row.get("location"):
            updated.pop("location", None)
        for field in ("language_note", "seniority_note", "domain_note"):
            if not row.get(field):
                updated.pop(field, None)
        seen[key] = updated
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def cmd_candidates(args) -> int:
    conn, _ = _open_conn(args)
    try:
        result = state_db.job_candidates(conn, show_all=args.all, focus=args.focus, limit=args.limit)
    finally:
        conn.close()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def cmd_sweep(args) -> int:
    conn, legacy_path = _open_conn(args)
    try:
        result = state_db.job_sweep(
            conn,
            write=args.write,
            exclude={item for item in (args.exclude or "").split(",") if item},
            today=args.today.isoformat(),
        )
        if legacy_path and args.write:
            _write_legacy(legacy_path, conn)
    finally:
        conn.close()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def cmd_apply(args) -> int:
    try:
        results = json.loads(Path(args.results).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise state_db.StateError(f"cannot read results file {args.results}: {exc}") from None
    if isinstance(results, dict):
        results = results.get("results", [])
    if not isinstance(results, list):
        raise state_db.StateError("results file must be a JSON array of scoring objects")
    conn, legacy_path = _open_conn(args)
    try:
        result = state_db.job_apply_rank(
            conn,
            results,
            today=args.today.isoformat(),
            now=args.now,
            dry_run=args.dry_run,
        )
        if legacy_path and not args.dry_run:
            _write_legacy(legacy_path, conn)
    finally:
        conn.close()
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 1 if result["errors"] else 0


def _force_utf8_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    _force_utf8_output()
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--state", type=Path, default=None)
    common.add_argument("--tracker", type=Path, default=None)
    common.add_argument("--db", type=Path, default=None)
    common.add_argument("--today", type=date.fromisoformat, default=date.today())

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    candidates = sub.add_parser("candidates", parents=[common])
    candidates.add_argument("--all", action="store_true")
    candidates.add_argument("--focus", default="")
    candidates.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    candidates.set_defaults(func=cmd_candidates)

    sweep = sub.add_parser("sweep", parents=[common])
    sweep.add_argument("--write", action="store_true")
    sweep.add_argument("--exclude", default="")
    sweep.set_defaults(func=cmd_sweep)

    apply_parser = sub.add_parser("apply", parents=[common])
    apply_parser.add_argument("--results", required=True)
    apply_parser.add_argument("--dry-run", action="store_true")
    apply_parser.add_argument("--now", default=None, help="ISO 8601 date-time used as the retry clock (default: now)")
    apply_parser.set_defaults(func=cmd_apply)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except state_db.StateError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
