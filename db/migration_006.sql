-- Drop watched_jobs table (created in migration_003, no longer used)
-- The job_scout design that used this table has been replaced.
-- seen_jobs (migration_002) is the live dedup table — do not touch it.
-- Governance tables from migration_001 are intentionally kept.
DROP TABLE IF EXISTS watched_jobs;
