-- ── Migration 007: public read access for the dashboard ──────────────────────
-- The React dashboard (dashboard/) is a read-only frontend that connects to
-- Supabase with the ANON key, so Row Level Security decides what it can see.
-- These policies allow public SELECT on the agent-data tables the dashboard
-- reads. This is a personal tool; these tables contain only the owner's own
-- agent outputs and run logs, no PII. Writes stay locked to service_role.
--
-- Note: RLS must be enabled on each table for these policies to take effect.
-- (enable is idempotent-safe to re-run.)

ALTER TABLE agent_runs    ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_outputs ENABLE ROW LEVEL SECURITY;
ALTER TABLE eval_results  ENABLE ROW LEVEL SECURITY;
ALTER TABLE holdings      ENABLE ROW LEVEL SECURITY;
ALTER TABLE seen_jobs     ENABLE ROW LEVEL SECURITY;

-- Allow public read access to agent data for the dashboard
-- This is a personal tool; these tables contain only the
-- owner's own agent outputs and run logs, no PII.
CREATE POLICY "allow_public_read_agent_runs"
  ON agent_runs FOR SELECT USING (true);
CREATE POLICY "allow_public_read_agent_outputs"
  ON agent_outputs FOR SELECT USING (true);
CREATE POLICY "allow_public_read_eval_results"
  ON eval_results FOR SELECT USING (true);
CREATE POLICY "allow_public_read_holdings"
  ON holdings FOR SELECT USING (true);
CREATE POLICY "allow_public_read_seen_jobs"
  ON seen_jobs FOR SELECT USING (true);
