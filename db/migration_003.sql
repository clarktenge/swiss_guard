CREATE TABLE watched_jobs (
  id uuid primary key default gen_random_uuid(),
  job_id text not null,
  company text not null,
  title text not null,
  url text not null,
  location text,
  reason text,
  added_at timestamptz not null default now(),
  unique(job_id, company)
);
GRANT ALL ON public.watched_jobs TO service_role;