PRAGMA foreign_keys = ON;

-- /rank: a posting that could not be fetched is `unreachable`, not `expired`,
-- and is retried on later runs. These columns keep the retry history and the
-- posting_guard verdict on the job row.
ALTER TABLE jobs ADD COLUMN fetch_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE jobs ADD COLUMN first_unreachable TEXT;
ALTER TABLE jobs ADD COLUMN last_fetch_error TEXT;
ALTER TABLE jobs ADD COLUMN expired_reason TEXT;
ALTER TABLE jobs ADD COLUMN guard TEXT;

PRAGMA user_version = 5;
