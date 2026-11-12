# Standard Read-Only Queries

Use `state_db query --sql "..."` or `state_db(action="query", sql="...")`.
All queries are read-only and return compact JSON. Prefer the views over raw
table joins.

## Funnel

```sql
SELECT
  COUNT(*) AS submitted,
  SUM(reached_interview) AS interviews,
  SUM(reached_offer) AS offers,
  SUM(resolved) AS resolved,
  SUM(rejected) AS rejected,
  SUM(no_response) AS no_response
FROM v_funnel
WHERE submitted = 1;
```

## Status breakdown

```sql
SELECT status, COUNT(*) AS n
FROM applications
GROUP BY status
ORDER BY n DESC;
```

## Cover-letter usage

```sql
SELECT
  cover_letter_used,
  COUNT(*) AS n,
  SUM(reached_interview) AS interviews,
  SUM(resolved) AS resolved
FROM v_cover_letter
GROUP BY cover_letter_used
ORDER BY cover_letter_used;
```

## Fit calibration

```sql
SELECT
  fit_band,
  COUNT(*) AS n,
  SUM(reached_interview) AS interviews
FROM v_fit_outcome
GROUP BY fit_band
ORDER BY fit_band;
```

## Response timing

```sql
SELECT
  COUNT(*) AS n,
  AVG(days_to_first_response) AS avg_days,
  MIN(days_to_first_response) AS min_days,
  MAX(days_to_first_response) AS max_days
FROM v_timing
WHERE days_to_first_response IS NOT NULL;
```

## Open applications

```sql
SELECT id, company, role, applied_on, status, last_stage, days_quiet
FROM v_open_pipeline
ORDER BY days_quiet DESC;
```

## Current application and timeline

```sql
SELECT id, company, role, status, applied_on, first_response_date,
       date_resolved, last_event_type, last_event_date, hh_state
FROM v_application_current
WHERE id = ?;
```

```sql
SELECT occurred_on, kind, summary, source
FROM v_application_timeline
WHERE application_id = ?
ORDER BY occurred_on, kind;
```

## External source references

```sql
SELECT source, external_type, external_id, last_state, last_seen_at
FROM application_sources
WHERE application_id = ?
ORDER BY source, external_type;
```

## Data quality

```sql
SELECT * FROM v_data_quality;
```

## Rules

- Do not use `SELECT *` from `applications` or `jobs` in a response unless the
  user explicitly asks for the full record.
- Add `LIMIT` for exploratory queries.
- Treat `unknown` as unknown, not as a negative observation.
- Do not infer response or rejection from a missing date.
