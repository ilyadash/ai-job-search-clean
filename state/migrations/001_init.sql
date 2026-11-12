PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS jobs (
    job_key TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    company TEXT NOT NULL DEFAULT '',
    company_norm TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    url_norm TEXT NOT NULL DEFAULT '',
    portal TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    first_seen TEXT,
    posted_date TEXT,
    deadline TEXT,
    status TEXT NOT NULL DEFAULT 'new',
    fit TEXT NOT NULL DEFAULT '',
    rank_score INTEGER,
    rank_verdict TEXT NOT NULL DEFAULT '',
    rank_date TEXT,
    location TEXT NOT NULL DEFAULT '',
    location_verdict TEXT NOT NULL DEFAULT '',
    language_gate TEXT NOT NULL DEFAULT '',
    language_note TEXT NOT NULL DEFAULT '',
    seniority_gate TEXT NOT NULL DEFAULT '',
    seniority_note TEXT NOT NULL DEFAULT '',
    domain_gate TEXT NOT NULL DEFAULT '',
    domain_note TEXT NOT NULL DEFAULT '',
    strengths_json TEXT NOT NULL DEFAULT '[]',
    gaps_json TEXT NOT NULL DEFAULT '[]',
    extra_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS jobs_status_idx ON jobs(status);
CREATE INDEX IF NOT EXISTS jobs_company_role_idx ON jobs(company_norm, title);
CREATE INDEX IF NOT EXISTS jobs_url_idx ON jobs(url_norm);

CREATE TABLE IF NOT EXISTS cv_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    label TEXT NOT NULL UNIQUE,
    path TEXT NOT NULL DEFAULT '',
    sha256 TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    is_current INTEGER NOT NULL DEFAULT 0 CHECK (is_current IN (0, 1))
);

CREATE TABLE IF NOT EXISTS applications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    applied_on TEXT,
    status TEXT NOT NULL DEFAULT 'drafted',
    company TEXT NOT NULL,
    company_norm TEXT NOT NULL,
    role TEXT NOT NULL,
    role_norm TEXT NOT NULL,
    sector TEXT NOT NULL DEFAULT '',
    role_type TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL DEFAULT '',
    contact_person TEXT NOT NULL DEFAULT '',
    fit_rating INTEGER CHECK (fit_rating IS NULL OR (fit_rating >= 0 AND fit_rating <= 100)),
    source_url TEXT NOT NULL DEFAULT '',
    deadline TEXT,
    notes TEXT NOT NULL DEFAULT '',
    cover_letter_used TEXT NOT NULL DEFAULT 'unknown'
        CHECK (cover_letter_used IN ('used', 'not_used', 'not_required', 'unknown')),
    cover_letter_path TEXT NOT NULL DEFAULT '',
    cover_letter_template TEXT NOT NULL DEFAULT '',
    cover_letter_words INTEGER,
    cv_version_id INTEGER REFERENCES cv_versions(id) ON DELETE SET NULL,
    cv_path TEXT NOT NULL DEFAULT '',
    first_response_date TEXT,
    date_resolved TEXT,
    job_key TEXT REFERENCES jobs(job_key) ON DELETE SET NULL,
    archive_path TEXT NOT NULL DEFAULT '',
    outcome_note_path TEXT NOT NULL DEFAULT '',
    origin TEXT NOT NULL DEFAULT 'legacy'
);

CREATE INDEX IF NOT EXISTS applications_status_idx ON applications(status);
CREATE INDEX IF NOT EXISTS applications_applied_on_idx ON applications(applied_on);
CREATE INDEX IF NOT EXISTS applications_company_role_idx ON applications(company_norm, role_norm);
CREATE INDEX IF NOT EXISTS applications_job_key_idx ON applications(job_key);

CREATE TABLE IF NOT EXISTS application_stages (
    application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    stage TEXT NOT NULL,
    reached INTEGER NOT NULL DEFAULT 1 CHECK (reached IN (0, 1)),
    date TEXT,
    source TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (application_id, stage)
);

CREATE INDEX IF NOT EXISTS application_stages_stage_idx ON application_stages(stage, reached);

CREATE TABLE IF NOT EXISTS application_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id INTEGER NOT NULL REFERENCES applications(id) ON DELETE CASCADE,
    event_date TEXT,
    event_type TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS application_events_app_idx ON application_events(application_id, event_date);

CREATE TABLE IF NOT EXISTS report_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_date TEXT NOT NULL,
    period_start TEXT,
    period_end TEXT,
    metrics_json TEXT NOT NULL DEFAULT '{}',
    report_path TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS experiments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    week_start TEXT NOT NULL,
    hypothesis TEXT NOT NULL DEFAULT '',
    change TEXT NOT NULL DEFAULT '',
    start_date TEXT,
    end_date TEXT,
    metric TEXT NOT NULL DEFAULT '',
    result TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'planned'
);

CREATE VIEW IF NOT EXISTS v_submitted AS
SELECT *
FROM applications
WHERE status NOT IN ('drafted', 'unknown');

CREATE VIEW IF NOT EXISTS v_funnel AS
SELECT
    a.*,
    CASE WHEN a.status IN ('drafted', 'unknown') THEN 0 ELSE 1 END AS submitted,
    CASE WHEN a.status IN ('drafted', 'unknown') THEN 0
         WHEN a.status IN ('interview', 'offer', 'hired', 'interview_only') THEN 1
         WHEN EXISTS (
             SELECT 1 FROM application_stages s
             WHERE s.application_id = a.id AND s.reached = 1
               AND s.stage IN ('phone_screen', 'technical', 'case', 'final', 'offer')
         ) THEN 1
         ELSE 0 END AS reached_interview,
    CASE WHEN a.status IN ('offer', 'hired') THEN 1
         WHEN EXISTS (
             SELECT 1 FROM application_stages s
             WHERE s.application_id = a.id AND s.reached = 1 AND s.stage = 'offer'
         ) THEN 1
         ELSE 0 END AS reached_offer,
    CASE WHEN a.status IN ('hired', 'rejected', 'no_response', 'offer_declined', 'withdrawn', 'interview_only') THEN 1 ELSE 0 END AS resolved,
    CASE WHEN a.status = 'rejected' THEN 1 ELSE 0 END AS rejected,
    CASE WHEN a.status = 'no_response' THEN 1 ELSE 0 END AS no_response,
    CASE WHEN a.status IN ('interview', 'offer', 'hired', 'interview_only') THEN 1 ELSE 0 END AS interview_status
FROM applications a;

CREATE VIEW IF NOT EXISTS v_cover_letter AS
SELECT
    a.id, a.company, a.role, a.status, a.applied_on, a.date_resolved,
    a.fit_rating, a.channel, a.origin, a.cover_letter_used,
    a.cover_letter_path, a.cover_letter_template, a.cover_letter_words,
    a.first_response_date, a.job_key,
    f.reached_interview, f.reached_offer, f.resolved, f.rejected, f.no_response
FROM applications a
JOIN v_funnel f ON f.id = a.id
WHERE a.status NOT IN ('drafted', 'unknown');

CREATE VIEW IF NOT EXISTS v_fit_outcome AS
SELECT
    a.id, a.company, a.role, a.status, a.applied_on, a.fit_rating,
    CASE
        WHEN a.fit_rating IS NULL THEN 'unknown'
        WHEN a.fit_rating >= 75 THEN 'strong'
        WHEN a.fit_rating >= 60 THEN 'good'
        WHEN a.fit_rating >= 45 THEN 'moderate'
        WHEN a.fit_rating >= 30 THEN 'weak'
        ELSE 'poor'
    END AS fit_band,
    f.reached_interview, f.reached_offer, f.resolved, f.rejected, f.no_response
FROM applications a
JOIN v_funnel f ON f.id = a.id
WHERE a.status NOT IN ('drafted', 'unknown');

CREATE VIEW IF NOT EXISTS v_timing AS
SELECT
    a.id, a.company, a.role, a.status, a.applied_on, a.first_response_date,
    a.date_resolved,
    CASE WHEN a.applied_on IS NOT NULL AND a.first_response_date IS NOT NULL
         THEN CAST(julianday(a.first_response_date) - julianday(a.applied_on) AS INTEGER)
         ELSE NULL END AS days_to_first_response,
    CASE WHEN a.applied_on IS NOT NULL AND a.date_resolved IS NOT NULL
         THEN CAST(julianday(a.date_resolved) - julianday(a.applied_on) AS INTEGER)
         ELSE NULL END AS days_to_resolution
FROM applications a
WHERE a.status NOT IN ('drafted', 'unknown');

CREATE VIEW IF NOT EXISTS v_weekly AS
SELECT
    a.applied_on,
    COUNT(*) AS applications,
    SUM(CASE WHEN f.reached_interview = 1 THEN 1 ELSE 0 END) AS interviews,
    SUM(CASE WHEN f.reached_offer = 1 THEN 1 ELSE 0 END) AS offers,
    SUM(CASE WHEN f.rejected = 1 THEN 1 ELSE 0 END) AS rejected,
    SUM(CASE WHEN f.no_response = 1 THEN 1 ELSE 0 END) AS no_response,
    SUM(CASE WHEN f.resolved = 0 THEN 1 ELSE 0 END) AS open
FROM applications a
JOIN v_funnel f ON f.id = a.id
WHERE a.applied_on IS NOT NULL
  AND a.status NOT IN ('drafted', 'unknown')
GROUP BY a.applied_on;

CREATE VIEW IF NOT EXISTS v_data_quality AS
SELECT
    (SELECT COUNT(*) FROM applications) AS applications,
    (SELECT COUNT(*) FROM applications WHERE status = 'drafted') AS drafted,
    (SELECT COUNT(*) FROM applications WHERE status = 'unknown') AS unknown_status,
    (SELECT COUNT(*) FROM applications WHERE cover_letter_used = 'unknown') AS cover_letter_unknown,
    (SELECT COUNT(*) FROM applications WHERE cv_version_id IS NULL) AS cv_version_unknown,
    (SELECT COUNT(*) FROM applications WHERE fit_rating IS NULL) AS fit_unknown,
    (SELECT COUNT(*) FROM applications WHERE first_response_date IS NULL) AS first_response_unknown,
    (SELECT COUNT(*) FROM applications WHERE date_resolved IS NULL AND status NOT IN ('drafted', 'unknown')) AS unresolved,
    (SELECT COUNT(*) FROM jobs) AS jobs,
    (SELECT COUNT(*) FROM jobs WHERE status = 'ranked') AS ranked_jobs;

PRAGMA user_version = 1;
