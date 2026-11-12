# /db - SQLite State by URL

Use the `state_db` typed tool for every state operation. The CLI fallback is
`python3 tools/state_db.py`. The database is `state/job_search.sqlite`; files
remain the memory for documents and narrative.

## Parse `$ARGUMENTS`

```text
/db show <url> [application_id=<id>]
/db update <url> [application_id=<id>] field=value ...
/db stats [markdown|json]
/db query <read-only SELECT>
```

Examples:

```text
/db show https://hh.ru/vacancy/123
/db update https://hh.ru/vacancy/123 status=rejected cover_letter_used=used
/db update https://hh.ru/vacancy/123 note="rejection email 2026-10-25"
/db stats
/db query "SELECT * FROM v_cover_letter LIMIT 20"
```

`/db update` fields:

`status`, `cover_letter_used`, `applied_on`, `first_response_date`,
`date_resolved`, `stage` (repeatable), `note`, `cv_version_id`, `cv_path`,
`archive_path`, `outcome_note_path`.

`applied_on=unknown` clears an inferred submission date; otherwise it must be
`YYYY-MM-DD`.

## Rules

1. Prefer `state_db(action="show")`/`state_db(action="update")`; use CLI only
   when the typed tool is unavailable.
2. URL is normalized and never fetched. Unknown URL is an error and no write.
3. If the result is `ambiguous`, stop and ask for `application_id`; never guess.
4. `update` changes only the application, its stages, and its events. Jobs are
   changed by `/scrape`/`/rank`, never by this command.
5. `query` is read-only. Never use SQL for INSERT/UPDATE/DELETE.
6. Show compact results; do not dump the database.
7. For the standard weekly report use `/weekly-review`, not ad-hoc SQL.
