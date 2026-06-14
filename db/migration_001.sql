-- ── Migration: eval system, governance, structured output ─────────────────────


-- ── 1. agent_runs — add eval tracking ────────────────────────────────────────
-- eval_status tells you at a glance whether the run passed all tier-1 checks.
-- Separate from 'status' (which tracks whether the agent ran without crashing)
-- because an agent can succeed technically but still fail its eval checks.
alter table agent_runs
  add column if not exists eval_status text default 'pending';
  -- values: pending | passed | failed | skipped


-- ── 2. agent_outputs — add structured output + governance class ───────────────
-- structured_output stores the validated Pydantic JSON.
-- content stays as the human-readable markdown sent to Discord.
-- governance_class is set by the classifier before anything downstream runs.
-- eval_passed is a quick boolean so the dashboard can filter without joining.
alter table agent_outputs
  add column if not exists structured_output jsonb,
  add column if not exists governance_class  text not null default 'READ_ONLY',
  add column if not exists eval_passed       boolean;


-- ── 3. eval_results — one row per check per run ───────────────────────────────
-- Every tier-1 and tier-2 check writes a row here.
-- This is what gives you the trend line over time:
-- "urgency precision has been drifting down since I changed the prompt on 6/15"
create table if not exists eval_results (
  id          uuid primary key default gen_random_uuid(),
  run_id      uuid not null references agent_runs(id) on delete cascade,
  agent_id    text not null,
  check_name  text not null,       -- e.g. 'conservation', 'gpa_consistency', 'urgency_precision'
  tier        integer not null,    -- 1 = deterministic, 2 = llm judge
  passed      boolean not null,
  score       real,                -- tier-2 judge score 0.0–1.0, null for tier-1
  reason      text,                -- what failed, or judge's explanation
  created_at  timestamptz not null default now()
);

-- Index for trend queries: "all conservation checks for email-triage over the last 30 days"
create index if not exists eval_results_agent_check
  on eval_results (agent_id, check_name, created_at desc);


-- ── 4. approvals — governance enforcement gate ────────────────────────────────
-- DRAFT and ACTION outputs write a row here before anything can execute.
-- The code that would execute an action checks this table first.
-- No approved row = no execution. This is the actual safety property.
create table if not exists approvals (
  id           uuid primary key default gen_random_uuid(),
  output_id    uuid not null references agent_outputs(id) on delete cascade,
  agent_id     text not null,
  action_type  text not null,      -- e.g. 'send_email', 'create_calendar_event'
  payload      jsonb not null,     -- the action that would be taken
  status       text not null default 'pending',  -- pending | approved | rejected
  reviewed_at  timestamptz
);

-- Index for the approval queue view: pending items, newest first
create index if not exists approvals_pending
  on approvals (status, id desc)
  where status = 'pending';


-- ── Grant permissions (same as original schema) ────────────────────────────────
grant all on public.eval_results to service_role;
grant all on public.approvals    to service_role;