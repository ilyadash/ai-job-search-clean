#!/usr/bin/env python3
"""Record /apply's draft in the SQLite state database and archive the posting."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import state_db
from tools.state_db import StateError

ROOT = Path(__file__).resolve().parent.parent
RecordError = StateError


def record_application(
    repo: Path | str = ROOT,
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
    today: str | None = None,
    cv_version_id: int | None = None,
    cv_path: str = "",
) -> dict:
    base = Path(repo)
    path = state_db.init_db(base)
    conn = state_db.connect(path)
    try:
        result = state_db.record_draft(
            conn,
            company=company,
            role=role,
            fit=fit,
            letter=letter,
            source=source,
            deadline=deadline,
            channel=channel,
            sector=sector,
            role_type=role_type,
            contact=contact,
            notes=notes,
            posting_file=posting_file,
            cv_version_id=cv_version_id,
            cv_path=cv_path,
            today=today,
            repo=base,
        )
    finally:
        conn.close()
    row = dict(result["row"])
    row["date"] = row.get("applied_on") or str(row.get("created_at") or "")[:10]
    row["cover_letter_file"] = row.get("cover_letter_path", "")
    row["cv_file"] = row.get("cv_path", "")
    row["source"] = row.get("source_url", "")
    row["fit_rating"] = "" if row.get("fit_rating") is None else str(row.get("fit_rating"))
    return {**result, "row": row}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record an /apply application")
    parser.add_argument("--company", default="")
    parser.add_argument("--role", default="")
    parser.add_argument("--fit", required=True, type=int)
    parser.add_argument("--letter", required=True)
    parser.add_argument("--source", default="")
    parser.add_argument("--deadline", default="")
    parser.add_argument("--channel", default="")
    parser.add_argument("--sector", default="")
    parser.add_argument("--role-type", default="", dest="role_type")
    parser.add_argument("--contact", default="")
    parser.add_argument("--notes", default="")
    parser.add_argument("--posting-file", default="", dest="posting_file")
    parser.add_argument("--cv-version", type=int)
    parser.add_argument("--cv-path", default="")
    args = parser.parse_args(argv)
    try:
        result = record_application(
            ROOT,
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
        )
    except RecordError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    row = result["row"]
    print(f"ACTION: {result['action']}")
    print(
        "ROW: "
        f"date={row.get('date', '')}, company={row.get('company', '')}, "
        f"role={row.get('role', '')}, status={row.get('status', '')}, "
        f"fit={row.get('fit_rating', '')}"
    )
    print(f"ARCHIVE: {result['archive']} {result['archive_path']}".rstrip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
