PRAGMA foreign_keys = ON;

DROP VIEW IF EXISTS v_application_timeline;

CREATE VIEW v_application_timeline AS
SELECT
    application_id,
    event_date AS occurred_on,
    event_type AS kind,
    text AS summary,
    source
FROM application_events
ORDER BY occurred_on, application_id;

PRAGMA user_version = 3;
