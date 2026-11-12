#!/usr/bin/env python3
"""Record a successful hh.ru response for /submit.

The browser step (``tools/hh_apply.py``) only *sends* the response; this script
writes the result to the SQLite state store in one transaction:

1. move the drafted application to ``applied`` (``application_update`` sets
   ``applied_on`` for a ``drafted -> applied`` transition and writes the
   ``submitted`` event);
2. store the hh negotiation (the actual response) in ``application_sources`` as
   ``source='hh', external_type='negotiation'``. The table already has a unique
   index on that pair, so the same response can never be attached to two
   applications.

It never creates an application and never touches ``jobs``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools import state_db
from tools.state_db import StateError

ROOT = Path(__file__).resolve().parent.parent
RecorderError = StateError

COVER_LETTER_VALUES = ("used", "not_used", "not_required", "unknown")


def record_submission(
    repo: Path | str = ROOT,
    *,
    url: str,
    response_id: str | None = None,
    cover_letter_used: str = "unknown",
    applied_on: str = "",
) -> dict:
    """Move the URL's application to ``applied`` and store its negotiation."""
    source = str(url or "").strip()
    if not source:
        raise RecorderError("url is required")
    if cover_letter_used not in COVER_LETTER_VALUES:
        raise RecorderError(f"cover_letter_used must be one of {COVER_LETTER_VALUES}")

    base = Path(repo)
    path = state_db.init_db(base)
    conn = state_db.connect(path)
    try:
        existing = state_db.find_application(conn, source=source)
        if existing is None:
            raise RecorderError(f"application not found for URL: {source}")
        app_id = int(existing["id"])
        # Insert the negotiation first: the unique index on
        # (source='hh', external_type='negotiation', external_id) raises here
        # before any status change is committed, so a duplicate response can
        # never half-apply. application_update commits both rows together.
        source_stored = ""
        if response_id:
            row = state_db.upsert_application_source(
                conn,
                app_id,
                source="hh",
                external_type="negotiation",
                external_id=str(response_id),
                url=source,
                last_state="applied",
            )
            source_stored = str(row.get("external_id") or "")
        result = state_db.application_update(
            conn,
            url=source,
            status="applied",
            cover_letter_used=cover_letter_used,
            applied_on=applied_on,
        )
        conn.commit()
    finally:
        conn.close()

    return {
        "status": "ok",
        "application_id": app_id,
        "changed": result.get("changed", []),
        "response_stored": source_stored,
        "cover_letter_used": cover_letter_used,
    }


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)  # absent on a StringIO under test
        if reconfigure:
            reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Record an hh.ru response for /submit")
    parser.add_argument("--url", required=True, help="hh.ru vacancy URL")
    parser.add_argument("--response-id", default="", dest="response_id")
    parser.add_argument(
        "--cover-letter-used",
        default="unknown",
        choices=COVER_LETTER_VALUES,
        dest="cover_letter_used",
    )
    parser.add_argument("--applied-on", default="", help="YYYY-MM-DD (default: today)")
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--repo", type=Path, default=ROOT)
    args = parser.parse_args(argv)

    try:
        result = record_submission(
            args.repo,
            url=args.url,
            response_id=args.response_id or None,
            cover_letter_used=args.cover_letter_used,
            applied_on=args.applied_on,
        )
    except StateError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.as_json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(f"APPLICATION_ID: {result['application_id']}")
        print(f"CHANGED: {', '.join(result['changed'])}")
        print(f"RESPONSE_STORED: {result['response_stored'] or '-'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
