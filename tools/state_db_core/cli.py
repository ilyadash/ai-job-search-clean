"""SQLite source of truth for job-search applications, jobs, and outcomes.

Command-line adapter for the state_db_core package.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .common import *
from .db import *
from .jobs import *
from .applications import *
from .outcomes import *
from .migration_text import *
from .migration_jobs import *
from .legacy_import import *
from .stats import *

def _print_json(value: object) -> None:
    print(json.dumps(value, indent=2, ensure_ascii=False))


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", type=Path, default=ROOT)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init")
    sub.add_parser("migrate")
    backfill = sub.add_parser("backfill-job-descriptions")
    backfill_mode = backfill.add_mutually_exclusive_group()
    backfill_mode.add_argument("--write", action="store_true")
    backfill_mode.add_argument("--dry-run", action="store_true")
    backfill.add_argument("--replace", action="store_true")
    backfill.add_argument("--limit", type=int, default=0)
    archived = sub.add_parser("backfill-archived-jobs")
    archived_mode = archived.add_mutually_exclusive_group()
    archived_mode.add_argument("--write", action="store_true")
    archived_mode.add_argument("--dry-run", action="store_true")
    archived.add_argument("--replace-description", action="store_true")
    text_migration = sub.add_parser("migrate-text-state")
    text_mode = text_migration.add_mutually_exclusive_group()
    text_mode.add_argument("--write", action="store_true")
    text_mode.add_argument("--dry-run", action="store_true")
    text_migration.add_argument("--strip-outcome", action="store_true")
    letter_meta = sub.add_parser("backfill-cover-letter-words")
    letter_mode = letter_meta.add_mutually_exclusive_group()
    letter_mode.add_argument("--write", action="store_true")
    letter_mode.add_argument("--dry-run", action="store_true")
    backup_parser = sub.add_parser("backup")
    backup_parser.add_argument("--destination", type=Path)

    sub.add_parser("schema")
    query_parser = sub.add_parser("query")
    query_parser.add_argument("--sql", required=True)
    query_parser.add_argument("--limit", type=int, default=500)

    stats_parser = sub.add_parser("stats")
    stats_parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    stats_parser.add_argument("--record-report", type=Path)

    import_parser = sub.add_parser("import-legacy")
    import_parser.add_argument("--tracker", type=Path)
    import_parser.add_argument("--seen", type=Path)
    import_parser.add_argument("--applications", type=Path)
    import_parser.add_argument("--force", action="store_true")

    job_upsert = sub.add_parser("job-upsert")
    job_upsert.add_argument("--file", type=Path, required=True)
    job_upsert.add_argument("--key")

    sub.add_parser("upskill-data")
    sub.add_parser("job-context")
    exists = sub.add_parser("job-exists")
    exists.add_argument("--url", default="")
    exists.add_argument("--company", default="")
    exists.add_argument("--title", default="")

    candidates = sub.add_parser("job-candidates")
    candidates.add_argument("--all", action="store_true")
    candidates.add_argument("--focus", default="")
    candidates.add_argument("--limit", type=int, default=10)

    sweep = sub.add_parser("job-sweep")
    sweep.add_argument("--write", action="store_true")
    sweep.add_argument("--exclude", default="")
    sweep.add_argument("--today")

    rank_apply = sub.add_parser("job-rank-apply")
    rank_apply.add_argument("--results", type=Path, required=True)
    rank_apply.add_argument("--today")
    rank_apply.add_argument("--dry-run", action="store_true")

    draft = sub.add_parser("application-draft")
    draft.add_argument("--company", required=True)
    draft.add_argument("--role", required=True)
    draft.add_argument("--fit", required=True, type=int)
    draft.add_argument("--letter", required=True)
    draft.add_argument("--source", default="")
    draft.add_argument("--deadline", default="")
    draft.add_argument("--channel", default="")
    draft.add_argument("--sector", default="")
    draft.add_argument("--role-type", default="", dest="role_type")
    draft.add_argument("--contact", default="")
    draft.add_argument("--notes", default="")
    draft.add_argument("--posting-file", default="", dest="posting_file")
    draft.add_argument("--cv-version", type=int)
    draft.add_argument("--cv-path", default="")

    outcome = sub.add_parser("application-outcome")
    outcome.add_argument("--company", required=True)
    outcome.add_argument("--role", required=True)
    outcome.add_argument("--status", required=True)
    outcome.add_argument("--source", default="")
    outcome.add_argument("--applied-on", default="", help="YYYY-MM-DD, or 'unknown' to leave empty")
    outcome.add_argument("--first-response-date", default="")
    outcome.add_argument("--date-resolved", default="")
    outcome.add_argument("--cover-letter-used", default="")
    outcome.add_argument("--cv-version", type=int)
    outcome.add_argument("--cv-path", default="")
    outcome.add_argument("--stage", action="append", default=[])
    outcome.add_argument("--note", default="")
    outcome.add_argument("--archive-path", default="")
    outcome.add_argument("--outcome-note-path", default="")
    outcome.add_argument("--no-create", action="store_true")

    lookup = sub.add_parser("application-lookup")
    lookup.add_argument("--source", default="")
    lookup.add_argument("--company", default="")
    lookup.add_argument("--role", default="")
    lookup.add_argument("--id", type=int)

    show = sub.add_parser("application-show")
    show.add_argument("--url", default="", dest="source")
    show.add_argument("--source", default="", dest="source")
    show.add_argument("--application-id", type=int)

    update = sub.add_parser("application-update")
    update.add_argument("--url", default="", dest="source")
    update.add_argument("--source", default="", dest="source")
    update.add_argument("--application-id", type=int)
    update.add_argument("--status", default="")
    update.add_argument("--cover-letter-used", default="")
    update.add_argument("--applied-on", default="")
    update.add_argument("--first-response-date", default="")
    update.add_argument("--date-resolved", default="")
    update.add_argument("--stage", action="append", default=[])
    update.add_argument("--note", default="")
    update.add_argument("--cv-version", type=int)
    update.add_argument("--cv-path", default="")
    update.add_argument("--archive-path", default="")
    update.add_argument("--outcome-note-path", default="")

    note = sub.add_parser("application-note")
    note.add_argument("--company", required=True)
    note.add_argument("--role", required=True)
    note.add_argument("--note", required=True)
    note.add_argument("--event-date", default="")
    note.add_argument("--source", default="manual")

    event_update = sub.add_parser("application-event-update")
    event_update.add_argument("--event-id", type=int, required=True)
    event_update.add_argument("--event-date", required=True)
    event_update.add_argument("--application-id", type=int)
    event_update.add_argument("--text", default="")

    event_delete = sub.add_parser("application-event-delete")
    event_delete.add_argument("--event-id", type=int, required=True)
    event_delete.add_argument("--application-id", type=int)

    listing = sub.add_parser("application-list")
    listing.add_argument("--open", action="store_true")

    sub.add_parser("quality")

    report = sub.add_parser("record-report")
    report.add_argument("--report-date", required=True)
    report.add_argument("--period-start", default="")
    report.add_argument("--period-end", default="")
    report.add_argument("--metrics-file", type=Path, required=True)
    report.add_argument("--report-path", required=True)

    args = parser.parse_args(argv)
    repo = args.repo
    try:
        if args.command == "init":
            print(init_db(repo))
            return 0
        if args.command == "migrate":
            _print_json(migrate(repo))
            return 0
        if args.command == "backup":
            print(backup(repo, args.destination))
            return 0
        if args.command == "import-legacy":
            _print_json(
                import_legacy(
                    repo=repo,
                    tracker=args.tracker,
                    seen=args.seen,
                    applications=args.applications,
                    force=args.force,
                )
            )
            return 0
        path = init_db(repo)
        if args.command == "backfill-job-descriptions":
            conn = connect(path)
            try:
                result = backfill_job_descriptions(
                    conn,
                    repo,
                    write=args.write,
                    replace=args.replace,
                    limit=args.limit,
                )
            finally:
                conn.close()
            _print_json(result)
            return 0
        if args.command == "backfill-archived-jobs":
            conn = connect(path)
            try:
                result = backfill_archived_jobs(
                    conn,
                    repo,
                    write=args.write,
                    replace_description=args.replace_description,
                )
            finally:
                conn.close()
            _print_json(result)
            return 0
        if args.command == "migrate-text-state":
            conn = connect(path)
            try:
                result = migrate_text_state(
                    conn,
                    repo,
                    write=args.write,
                    strip_outcome=args.strip_outcome,
                )
            finally:
                conn.close()
            _print_json(result)
            return 0
        if args.command == "backfill-cover-letter-words":
            conn = connect(path)
            try:
                result = backfill_cover_letter_words(conn, repo, write=args.write)
            finally:
                conn.close()
            _print_json(result)
            return 0
        if args.command == "schema":
            conn = connect(path, readonly=True)
            try:
                print(schema_text(conn), end="")
            finally:
                conn.close()
            return 0
        if args.command == "query":
            _print_json(query(args.sql, limit=args.limit, repo=repo))
            return 0
        if args.command == "stats":
            conn = connect(path, readonly=True)
            try:
                data = compute_stats(conn)
            finally:
                conn.close()
            if args.format == "json":
                _print_json(data)
            else:
                print(stats_markdown(data), end="")
            if args.record_report:
                conn = connect(path)
                try:
                    record_report(
                        conn,
                        report_date=_today(),
                        period_start="",
                        period_end="",
                        metrics=data,
                        report_path=args.record_report.as_posix(),
                    )
                finally:
                    conn.close()
            return 0
        if args.command == "job-upsert":
            payload = json.loads(args.file.read_text(encoding="utf-8"))
            entries = payload if isinstance(payload, list) else [payload]
            conn = connect(path)
            try:
                results = [upsert_job(conn, entry, key=args.key) for entry in entries]
                conn.commit()
            finally:
                conn.close()
            _print_json({"written": len(results), "jobs": results})
            return 0
        if args.command == "upskill-data":
            conn = connect(path, readonly=True)
            try:
                _print_json(upskill_data(conn))
            finally:
                conn.close()
            return 0
        if args.command == "job-context":
            conn = connect(path, readonly=True)
            try:
                _print_json(job_context(conn))
            finally:
                conn.close()
            return 0
        if args.command == "job-exists":
            conn = connect(path, readonly=True)
            try:
                _print_json(job_exists(conn, url=args.url, company=args.company, title=args.title))
            finally:
                conn.close()
            return 0
        if args.command == "job-candidates":
            conn = connect(path)
            try:
                _print_json(job_candidates(conn, show_all=args.all, focus=args.focus, limit=args.limit))
            finally:
                conn.close()
            return 0
        if args.command == "job-sweep":
            conn = connect(path)
            try:
                _print_json(job_sweep(conn, write=args.write, exclude={item for item in args.exclude.split(",") if item}, today=args.today))
            finally:
                conn.close()
            return 0
        if args.command == "job-rank-apply":
            results = json.loads(args.results.read_text(encoding="utf-8"))
            if isinstance(results, dict):
                results = results.get("results", [])
            conn = connect(path)
            try:
                _print_json(job_apply_rank(conn, results, today=args.today, dry_run=args.dry_run))
            finally:
                conn.close()
            return 0
        if args.command == "application-draft":
            conn = connect(path)
            try:
                result = record_draft(
                    conn,
                    company=args.company,
                    role=args.role,
                    fit=args.fit,
                    letter=args.letter,
                    source=args.source,
                    deadline=args.deadline,
                    channel=args.channel,
                    sector=args.sector,
                    role_type=args.role_type,
                    contact=args.contact,
                    notes=args.notes,
                    posting_file=args.posting_file or None,
                    cv_version_id=args.cv_version,
                    cv_path=args.cv_path,
                    repo=repo,
                )
            finally:
                conn.close()
            _print_json(result)
            return 0
        if args.command == "application-outcome":
            conn = connect(path)
            try:
                result = record_outcome(
                    conn,
                    company=args.company,
                    role=args.role,
                    status=args.status,
                    source=args.source,
                    applied_on=args.applied_on,
                    first_response_date=args.first_response_date,
                    date_resolved=args.date_resolved,
                    cover_letter_used=args.cover_letter_used,
                    cv_version_id=args.cv_version,
                    cv_path=args.cv_path,
                    stages=args.stage,
                    note=args.note,
                    archive_path=args.archive_path,
                    outcome_note_path=args.outcome_note_path,
                    create=not args.no_create,
                )
            finally:
                conn.close()
            _print_json(result)
            return 0
        if args.command == "application-lookup":
            conn = connect(path, readonly=True)
            try:
                if args.id:
                    row = _application_row(conn, args.id)
                    result = _application_payload(conn, row) if row else None
                else:
                    result = find_application(conn, source=args.source, company=args.company, role=args.role)
            finally:
                conn.close()
            _print_json(result)
            return 0
        if args.command == "application-show":
            conn = connect(path, readonly=True)
            try:
                _print_json(application_show(conn, url=args.source, application_id=args.application_id))
            finally:
                conn.close()
            return 0
        if args.command == "application-update":
            conn = connect(path)
            try:
                result = application_update(
                    conn,
                    url=args.source,
                    application_id=args.application_id,
                    status=args.status,
                    cover_letter_used=args.cover_letter_used,
                    applied_on=args.applied_on,
                    first_response_date=args.first_response_date,
                    date_resolved=args.date_resolved,
                    stages=args.stage,
                    note=args.note,
                    cv_version_id=args.cv_version,
                    cv_path=args.cv_path,
                    archive_path=args.archive_path,
                    outcome_note_path=args.outcome_note_path,
                )
            finally:
                conn.close()
            _print_json(result)
            return 0
        if args.command == "application-note":
            conn = connect(path)
            try:
                result = add_application_note(
                    conn,
                    company=args.company,
                    role=args.role,
                    note=args.note,
                    event_date=args.event_date,
                    source=args.source,
                )
            finally:
                conn.close()
            _print_json(result)
            return 0
        if args.command == "application-event-update":
            conn = connect(path)
            try:
                result = update_application_event(
                    conn,
                    event_id=args.event_id,
                    event_date=args.event_date,
                    application_id=args.application_id,
                    text=args.text,
                )
            finally:
                conn.close()
            _print_json(result)
            return 0
        if args.command == "application-event-delete":
            conn = connect(path)
            try:
                result = delete_application_event(
                    conn,
                    event_id=args.event_id,
                    application_id=args.application_id,
                )
            finally:
                conn.close()
            _print_json(result)
            return 0
        if args.command == "application-list":
            conn = connect(path, readonly=True)
            try:
                _print_json(list_applications(conn, open_only=args.open))
            finally:
                conn.close()
            return 0
        if args.command == "quality":
            conn = connect(path, readonly=True)
            try:
                data = compute_stats(conn)["quality"]
            finally:
                conn.close()
            _print_json(data)
            return 0
        if args.command == "record-report":
            metrics = json.loads(args.metrics_file.read_text(encoding="utf-8"))
            conn = connect(path)
            try:
                report_id = record_report(
                    conn,
                    report_date=args.report_date,
                    period_start=args.period_start,
                    period_end=args.period_end,
                    metrics=metrics,
                    report_path=args.report_path,
                )
            finally:
                conn.close()
            _print_json({"id": report_id})
            return 0
    except (StateError, OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    sys.exit(main())

__all__ = [name for name in globals() if not name.startswith("__")]
