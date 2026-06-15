-- ── Migration 002: job-scout seen_jobs ───────────────────────────────────────
-- One row per job the job-scout agent has ever seen, keyed by (job_id, company).
-- The agent records a job here the FIRST time it sees it — before relevance
-- filtering — so a role is never surfaced twice even if it failed the filter on
-- the first pass. The unique(job_id, company) constraint is what makes
-- "have I seen this?" a single cheap lookup and dedupes across runs.

create table if not exists seen_jobs (
  id         uuid primary key default gen_random_uuid(),
  job_id     text not null,
  company    text not null,
  title      text not null,
  url        text not null,
  source     text not null,            -- ats type: greenhouse | lever | ashby | custom
  found_at   timestamptz not null default now(),
  unique(job_id, company)
);

-- Lookup path the agent uses every run: "which of these job_ids do I already
-- have for this company?" The unique constraint already covers (job_id, company)
-- so no extra index is needed.

grant all on public.seen_jobs to service_role;
