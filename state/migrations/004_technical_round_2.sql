PRAGMA foreign_keys = ON;

DROP VIEW IF EXISTS v_cover_letter;
DROP VIEW IF EXISTS v_fit_outcome;
DROP VIEW IF EXISTS v_weekly;
DROP VIEW IF EXISTS v_funnel;

CREATE VIEW v_funnel AS
SELECT
    a.*,
    CASE WHEN a.status IN ('drafted', 'unknown') THEN 0 ELSE 1 END AS submitted,
    CASE WHEN a.status IN ('drafted', 'unknown') THEN 0
         WHEN a.status IN ('interview', 'offer', 'hired', 'interview_only') THEN 1
         WHEN EXISTS (
             SELECT 1 FROM application_stages s
             WHERE s.application_id = a.id AND s.reached = 1
               AND s.stage IN ('phone_screen', 'technical', 'technical_2', 'case', 'final', 'offer')
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

CREATE VIEW v_cover_letter AS
SELECT
    a.id, a.company, a.role, a.status, a.applied_on, a.date_resolved,
    a.fit_rating, a.channel, a.origin, a.cover_letter_used,
    a.cover_letter_path, a.cover_letter_template, a.cover_letter_words,
    a.first_response_date, a.job_key,
    f.reached_interview, f.reached_offer, f.resolved, f.rejected, f.no_response
FROM applications a
JOIN v_funnel f ON f.id = a.id
WHERE a.status NOT IN ('drafted', 'unknown');

CREATE VIEW v_fit_outcome AS
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

CREATE VIEW v_weekly AS
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

PRAGMA user_version = 4;
