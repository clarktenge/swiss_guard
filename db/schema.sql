-- Enable pgvector (run this first)
create extension if not exists vector;

-- ── Agent runs ────────────────────────────────────────────────────────────────
-- Every time an agent fires, win or lose, it gets a row here.
create table agent_runs (
  id            uuid primary key default gen_random_uuid(),
  agent_id      text not null,
  status        text not null default 'running', -- running | success | error
  started_at    timestamptz not null default now(),
  finished_at   timestamptz,
  latency_ms    integer,
  error_message text
);

-- ── Agent outputs ─────────────────────────────────────────────────────────────
-- The actual content each agent produces, plus its vector embedding for memory.
create table agent_outputs (
  id         uuid primary key default gen_random_uuid(),
  run_id     uuid references agent_runs(id) on delete cascade,
  agent_id   text not null,
  content    text not null,
  embedding  vector(1024),          -- voyage-3 produces 1024-dim vectors
  metadata   jsonb default '{}',
  created_at timestamptz not null default now()
);

-- ── Portfolio holdings ────────────────────────────────────────────────────────
create table holdings (
  id        uuid primary key default gen_random_uuid(),
  ticker    text not null unique,
  shares    numeric not null,
  avg_cost  numeric not null,
  notes     text,
  added_at  timestamptz not null default now()
);

-- ── Indexes ───────────────────────────────────────────────────────────────────
-- Speed up the most common dashboard queries
create index on agent_runs (agent_id, started_at desc);
create index on agent_outputs (agent_id, created_at desc);

-- Vector index for semantic memory search
create index on agent_outputs
  using ivfflat (embedding vector_cosine_ops)
  with (lists = 100);

-- ── Memory search function ────────────────────────────────────────────────────
-- Called by recall_memory() in base.py
-- Returns the most semantically similar past outputs for a given agent
create or replace function match_agent_outputs(
  query_embedding  vector(1024),
  agent_id_filter  text,
  match_count      int default 3
)
returns table (
  id         uuid,
  content    text,
  metadata   jsonb,
  created_at timestamptz,
  similarity float
)
language sql stable
as $$
  select
    id,
    content,
    metadata,
    created_at,
    1 - (embedding <=> query_embedding) as similarity
  from agent_outputs
  where agent_id = agent_id_filter
    and embedding is not null
  order by embedding <=> query_embedding
  limit match_count;
$$;