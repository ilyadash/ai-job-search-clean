---
name: state-db
version: 1.0.0
description: >
  Works with the SQLite job-search state database: show or update an application
  by vacancy URL, read standard funnel/cover-letter metrics, or run read-only SQL
  against views. Trigger phrases: state database, SQLite, database state, show
  application, update application, update by URL, job status, funnel stats,
  cover letter stats, состояние базы, обнови отклик по ссылке, покажи отклик,
  статистика откликов, SQL-запрос.
allowed-tools: Read, Grep, Bash(python3 tools/state_db.py:*), Bash(python tools/state_db.py:*), state_db
---

# SQLite State

`state/job_search.sqlite` is the source of truth for structured state:
applications, jobs, stages, events, outcomes, cover-letter usage, CV versions,
and review metrics. Documents and narrative stay on disk.

Prefer the typed tool `state_db`; if it is unavailable, use the CLI. Never read
the database file or load the whole schema into context.

## Routing

| Task | Use |
|---|---|
| Show the application/job for a URL | `state_db(action="show", url=...)` |
| Update an application by URL | `state_db(action="update", url=..., ...)` |
| Correct a recorded event date | CLI `application-event-update --event-id ... --event-date ...` |
| Delete an erroneous auto-generated event | CLI `application-event-delete --event-id ...` |
| Standard weekly metrics | `state_db(action="stats", format="markdown")` |
| Current application state | `state_db(action="query", sql="SELECT * FROM v_application_current WHERE id = ...")` |
| Application timeline | `state_db(action="query", sql="SELECT * FROM v_application_timeline WHERE application_id = ...")` |
| Open pipeline | `state_db(action="query", sql="SELECT * FROM v_open_pipeline ORDER BY days_quiet DESC")` |
| Ad-hoc read-only analysis | `state_db(action="query", sql="SELECT ...")` |
| Scrape/rank pipeline state | existing `/scrape`, `/rank`, `job-context`, `job-upsert` |

CLI equivalents:

```bash
python3 tools/state_db.py migrate
python3 tools/state_db.py backfill-job-descriptions --dry-run
python3 tools/state_db.py backfill-archived-jobs --dry-run
python3 tools/state_db.py migrate-text-state --dry-run
python3 tools/state_db.py backfill-cover-letter-words --dry-run
python3 tools/state_db.py application-show --url "<url>"
python3 tools/state_db.py application-update --url "<url>" --status rejected
python3 tools/state_db.py application-event-update --event-id 171 --event-date 2026-10-28
python3 tools/state_db.py application-event-delete --event-id 171
python3 tools/state_db.py stats --format markdown
python3 tools/state_db.py query --sql "SELECT * FROM v_cover_letter"
```

## URL-first workflow

1. Run `show` with the exact URL supplied by the user. URL normalization handles
   tracking parameters and trailing slashes; it never fetches the page.
2. If `status` is `ambiguous`, stop and return the candidate list. Ask for the
   application id; do not guess company or role.
3. If `status` is `job_only`, the vacancy is known but no application exists.
   Do not create one from an update; use the existing application workflow.
4. If `status` is `not_found`, stop and say the URL is not tracked.
5. For an update, pass only the fields that changed. The command updates the
   application, its stages, and its events in one transaction. It never updates
   the jobs table.

## Mutation rules

- No `INSERT`, `UPDATE`, `DELETE`, `PRAGMA`, or `ATTACH` through SQL.
- No ad-hoc SQL writes. If a mutation is missing, add a domain command.
- `application-update` never creates an application and never touches jobs.
- `application_sources` maps external IDs; `last_state` is a cache, not the
  local application status. Event history belongs in `application_events`.
- Dated notes and status history belong in `application_events`;
  `applications.notes` is undated context only. `outcome.md` is narrative only.
- `backfill-archived-jobs` creates `jobs.status='archived'` rows for historical
  applications. Archived jobs are seen by `/scrape`, never ranked, and never
  swept.
- Do not change cover-letter usage from a file's presence; use `used`,
  `not_used`, `not_required`, or `unknown` only when known.
- Do not infer dates. Leave a field empty when unknown; pass
  `applied_on="unknown"` to clear a wrongly inferred submission date.
- `query` is read-only and accepts only `SELECT`/`WITH`/`EXPLAIN` with a row
  limit; it cannot mutate state.

## Token discipline

- Keep outputs compact: the tool returns one application plus related job/stages,
  not the whole database.
- Read `schema.md` only when a non-standard query needs table/column names.
- Read `queries.md` only for a named analytical pattern.
- Use `stats` and the `v_*` views instead of repeating SQL for standard metrics.
- Do not load another skill from this skill; reference files are enough.
- Do not paste raw database rows into the final answer unless the user asks for
  a specific record.

## References

- `schema.md` — compact tables, columns, statuses, views.
- `queries.md` — standard read-only query patterns.
