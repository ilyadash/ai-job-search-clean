PRAGMA foreign_keys = ON;

ALTER TABLE jobs ADD COLUMN description_text TEXT NOT NULL DEFAULT '';
ALTER TABLE jobs ADD COLUMN description_hash TEXT NOT NULL DEFAULT '';
ALTER TABLE jobs ADD COLUMN description_fetched_at TEXT;
ALTER TABLE jobs ADD COLUMN language TEXT NOT NULL DEFAULT '';

ALTER TABLE application_events ADD COLUMN recorded_at TEXT NOT NULL DEFAULT '';
ALTER TABLE application_events ADD COLUMN external_ref TEXT NOT NULL DEFAULT '';
ALTER TABLE application_events ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}';

UPDATE application_events
SET recorded_at = COALESCE(NULLIF(event_date, ''), datetime('now'))
WHERE recorded_at = '';

CREATE TABLE IF NOT EXISTS application_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL
        REFERENCES applications(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    external_type TEXT NOT NULL,
    external_id TEXT NOT NULL,
    url TEXT NOT NULL DEFAULT '',
    last_state TEXT NOT NULL DEFAULT '',
    last_seen_at TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(application_id, source, external_type, external_id)
);

CREATE INDEX IF NOT EXISTS application_sources_app_idx
    ON application_sources(application_id);
CREATE INDEX IF NOT EXISTS application_sources_lookup_idx
    ON application_sources(source, external_type, external_id);
CREATE UNIQUE INDEX IF NOT EXISTS application_sources_hh_negotiation_idx
    ON application_sources(source, external_type, external_id)
    WHERE source = 'hh' AND external_type = 'negotiation';

CREATE TABLE IF NOT EXISTS sync_state (
    source TEXT PRIMARY KEY,
    cursor TEXT NOT NULL DEFAULT '',
    last_sync_at TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE VIEW IF NOT EXISTS v_application_current AS
SELECT
    a.id,
    a.company,
    a.role,
    a.status,
    a.applied_on,
    a.first_response_date,
    a.date_resolved,
    a.fit_rating,
    a.cover_letter_used,
    a.source_url,
    a.job_key,
    a.origin,
    a.created_at,
    a.updated_at,
    (SELECT MAX(e.event_date) FROM application_events e
     WHERE e.application_id = a.id) AS last_event_date,
    (SELECT e.event_type FROM application_events e
     WHERE e.application_id = a.id
     ORDER BY COALESCE(e.event_date, '') DESC, e.id DESC LIMIT 1) AS last_event_type,
    (SELECT e.text FROM application_events e
     WHERE e.application_id = a.id
     ORDER BY COALESCE(e.event_date, '') DESC, e.id DESC LIMIT 1) AS last_event_text,
    (SELECT s.stage FROM application_stages s
     WHERE s.application_id = a.id AND s.reached = 1
     ORDER BY COALESCE(s.date, '') DESC, s.stage DESC LIMIT 1) AS last_stage,
    (SELECT s.date FROM application_stages s
     WHERE s.application_id = a.id AND s.reached = 1
     ORDER BY COALESCE(s.date, '') DESC, s.stage DESC LIMIT 1) AS last_stage_date,
    (SELECT COUNT(*) FROM application_sources src
     WHERE src.application_id = a.id) AS source_count,
    (SELECT src.last_state FROM application_sources src
     WHERE src.application_id = a.id AND src.source = 'hh'
     ORDER BY COALESCE(src.last_seen_at, '') DESC, src.id DESC LIMIT 1) AS hh_state,
    CASE
        WHEN a.applied_on IS NULL THEN NULL
        ELSE CAST(julianday('now') - julianday(COALESCE(
            (SELECT MAX(e.event_date) FROM application_events e
             WHERE e.application_id = a.id),
            a.applied_on
        )) AS INTEGER)
    END AS days_quiet
FROM applications a;

CREATE VIEW IF NOT EXISTS v_application_timeline AS
SELECT
    application_id,
    event_date AS occurred_on,
    event_type AS kind,
    text AS summary,
    source
FROM application_events
UNION ALL
SELECT
    application_id,
    date AS occurred_on,
    'stage:' || stage AS kind,
    'Stage reached: ' || stage AS summary,
    source
FROM application_stages
WHERE reached = 1 AND date IS NOT NULL AND date <> ''
ORDER BY occurred_on, application_id;

CREATE VIEW IF NOT EXISTS v_open_pipeline AS
SELECT
    a.id,
    a.company,
    a.role,
    a.status,
    a.applied_on,
    a.first_response_date,
    a.source_url,
    a.fit_rating,
    a.cover_letter_used,
    (SELECT MAX(e.event_date) FROM application_events e
     WHERE e.application_id = a.id) AS last_event_date,
    (SELECT s.stage FROM application_stages s
     WHERE s.application_id = a.id AND s.reached = 1
     ORDER BY COALESCE(s.date, '') DESC, s.stage DESC LIMIT 1) AS last_stage,
    (SELECT s.date FROM application_stages s
     WHERE s.application_id = a.id AND s.reached = 1
     ORDER BY COALESCE(s.date, '') DESC, s.stage DESC LIMIT 1) AS last_stage_date,
    CASE
        WHEN a.applied_on IS NULL THEN NULL
        ELSE CAST(julianday('now') - julianday(COALESCE(
            (SELECT MAX(e.event_date) FROM application_events e
             WHERE e.application_id = a.id),
            a.applied_on
        )) AS INTEGER)
    END AS days_quiet
FROM applications a
WHERE a.status NOT IN (
    'drafted', 'unknown', 'hired', 'rejected', 'no_response',
    'offer_declined', 'withdrawn', 'interview_only'
);

PRAGMA user_version = 2;
