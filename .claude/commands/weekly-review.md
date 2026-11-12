# /weekly-review - Weekly Funnel and Cover-Letter Review

You are producing a weekly, evidence-based review of the job search. The database is the source of truth. Use the deterministic metrics first, then run only the read-only SQL needed to answer the user's focus. Print Markdown tables in the chat and save the same report under `reports/` for history.

This command never edits applications, jobs, the profile, or the evaluation framework. It writes only the report and one `report_runs` row.

## Step 0: Prepare

1. Run:
   ```bash
   python3 tools/state_db.py backup
   mkdir -p reports
   ```
2. Capture the data timestamp:
   ```bash
   python3 tools/state_db.py query --sql "SELECT datetime('now') AS now"
   ```
3. Run the standard metrics:
   ```bash
   python3 tools/state_db.py stats --format markdown
   python3 tools/state_db.py stats --format json
   ```
   Save the JSON output to a temp file outside the repository, for example:
   ```bash
   python3 tools/state_db.py stats --format json > /tmp/weekly-metrics.json
   ```

## Step 1: Read the Tables

Use the Markdown output as the base of the report. It already covers:

- data coverage: submitted, drafts, unknown, resolved, open;
- funnel: submitted → response → interview → offer, with n and Wilson 95% CI;
- rejection/no-response among resolved;
- cover letter: used / not_used / not_required / unknown, with response and interview rates;
- fit buckets vs interview rate;
- weekly activity;
- response timing;
- missing/unknown fields.

Do not recompute these numbers by reading raw rows. If a number is missing, say so.

## Step 2: Answer the User's Focus with Read-Only SQL

The user may add a focus after the command, for example:
- "why no offers"
- "does the cover letter help"
- "which roles are worth targeting"
- "what changed this week"

Use `python3 tools/state_db.py query --sql "SELECT ..."` against the views. Useful views:

- `v_funnel` — application status, stage reached, resolved/rejected flags;
- `v_cover_letter` — submitted applications with `cover_letter_used`, origin, channel, fit, interview/response flags;
- `v_fit_outcome` — fit buckets vs interview;
- `v_timing` — days to first response/resolution;
- `v_weekly` — per-date activity (aggregate by week in SQL if needed);
- `v_data_quality` — coverage.

Rules for SQL:

- Read-only `SELECT`/`WITH` only.
- Always show `n`; never present a rate without its denominator.
- Treat `unknown` as unknown, not as `not_used`.
- Do not make causal claims from a handful of rows. Label findings as observation, hypothesis, or insufficient evidence.
- The cover-letter historical field is mostly `unknown`; the first reports can show coverage, not an effect. Say so plainly.

## Step 3: Write the Report

Use this structure:

```markdown
# Weekly review - YYYY-MM-DD

Data as of: <timestamp>

## TL;DR
- Where the funnel breaks.
- What the evidence supports.
- The one or two actions for next week.

## Data coverage
<table from stats>

## Funnel
<table from stats>
- Bottleneck: ...
- What is still unresolved: ...

## Cover letter
<table from stats>
- Coverage: ...
- Evidence: ...
- Verdict: insufficient evidence / directional / not measurable yet.

## Fit calibration
<table from stats>

## Weekly activity
<table from stats>

## Timing
<table from stats>

## What this suggests
- Observation: ...
- Hypothesis: ...
- Confidence: high / medium / low / insufficient data.

## Next experiments
1. ...
2. ...

## Appendix
- Metric definitions: response = explicit rejection, interview, offer, hired, offer_declined, or interview_only; no_response is not a response.
- SQL used: <short list or notes>
- Known limitations: small n, missing fields, CV change on 2026-10-05, historical cover-letter usage unknown.
```

Keep the chat output to the tables and a short analysis. Do not paste raw JSON.

## Step 4: Save and Record

1. Write the report to `reports/weekly-YYYY-MM-DD.md`.
2. Record the metrics:
   ```bash
   python3 tools/state_db.py record-report \
     --report-date YYYY-MM-DD \
     --period-start <YYYY-MM-DD> --period-end <YYYY-MM-DD> \
     --metrics-file /tmp/weekly-metrics.json \
     --report-path reports/weekly-YYYY-MM-DD.md
   ```
3. In the chat, summarize the bottleneck, the cover-letter verdict, and the next experiments. Link the saved report path.

## Guardrails

- No `INSERT`, `UPDATE`, `DELETE`, `PRAGMA`, `ATTACH`, or schema changes through the report.
- `state_db.py query` is read-only; use it for every ad hoc question.
- Do not edit `job_search_tracker.csv` or `job_scraper/seen_jobs.json`; they are retired.
- Do not edit `04-job-evaluation.md` or `01-candidate-profile.md`; calibration belongs to `/setup`.
- If the database is missing, restore it from `backups/` or run `python3 tools/state_db.py import-legacy --tracker <legacy tracker> --seen <legacy seen_jobs> --applications documents/applications`.
