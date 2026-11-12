# State Database Schema

Database: `state/job_search.sqlite`

Use `python3 tools/state_db.py schema` for the authoritative live schema. This
reference is a compact map for choosing commands and writing read-only SQL.

## applications

One row per application. Important columns:

`id`, `created_at`, `updated_at`, `applied_on`, `status`, `company`,
`company_norm`, `role`, `role_norm`, `sector`, `role_type`, `channel`,
`contact_person`, `fit_rating`, `source_url`, `deadline`, `notes`,
`cover_letter_used`, `cover_letter_path`, `cover_letter_template`,
`cover_letter_words`, `cv_version_id`, `cv_path`, `first_response_date`,
`date_resolved`, `job_key`, `archive_path`, `outcome_note_path`, `origin`.

`notes` is undated context only. Dated history belongs in `application_events`;
the pipeline does not copy event text into `notes`.

Statuses:

`drafted`, `applied`, `interview`, `offer`, `hired`, `rejected`,
`no_response`, `offer_declined`, `withdrawn`, `interview_only`, `unknown`.

`cover_letter_used`: `used`, `not_used`, `not_required`, `unknown`.

## application_stages

`application_id`, `stage`, `reached`, `date`, `source`.

Stages: `phone_screen`, `technical`, `technical_2`, `case`, `final`, `offer`.
`technical_2` is recorded only when a real second technical round exists; a
single-round technical loop leaves it unset.

## application_events

`id`, `application_id`, `event_date`, `event_type`, `text`, `source`,
`recorded_at`, `external_ref`, `metadata_json`.

`event_date` is the business date; `recorded_at` is when the row was written.
Canonical event types include `submitted`, `response_received`,
`interview_status`, `stage_reached`, `offer_received`, `rejected`,
`no_response`, `withdrawn`, `note`, and `status_changed`.

## jobs

One row per vacancy, keyed by `job_key`:

`title`, `company`, `company_norm`, `url`, `url_norm`, `portal`, `source`,
`first_seen`, `posted_date`, `deadline`, `status`, `fit`, `rank_score`,
`rank_verdict`, `rank_date`, `location`, `location_verdict`,
`language_gate`, `language_note`, `seniority_gate`, `seniority_note`,
`domain_gate`, `domain_note`, `strengths_json`, `gaps_json`,
`description_text`, `description_hash`, `description_fetched_at`, `language`.

Job status is the scrape lifecycle (`new`, `skipped`, `ranked`, `expired`) plus
`archived` for historical postings recovered from application archives. Archived
jobs count as seen for scrape dedupe, are never ranked, and are never swept.
Application updates never change jobs' lifecycle status.

## application_sources

External identities for an application:

`id`, `application_id`, `source`, `external_type`, `external_id`, `url`,
`last_state`, `last_seen_at`, `metadata_json`, `created_at`, `updated_at`.

`source` is `hh`, `linkedin`, or `manual`; `external_type` is
`vacancy`, `negotiation`, `message`, or `thread`. The table is a cache of
external IDs and last known external state, not an event history. A vacancy may
belong to several applications; one HH negotiation belongs to one application.

## sync_state

`source`, `cursor`, `last_sync_at`, `metadata_json`.

## cv_versions

`id`, `label`, `path`, `sha256`, `created_at`, `is_current`.

## report_runs / experiments

`report_runs` stores weekly metrics and the report path. `experiments` reserves
the learning-plan/experiment log; it is not part of URL application updates.

## Views

- `v_funnel` — application status, stage reached, resolved/rejected flags.
- `v_cover_letter` — submitted applications + cover-letter usage and rates.
- `v_fit_outcome` — fit buckets vs interview.
- `v_timing` — days to first response/resolution.
- `v_weekly` — activity grouped by applied date.
- `v_data_quality` — missing/unknown coverage.
- `v_submitted` — applications excluding `drafted` and `unknown`.
