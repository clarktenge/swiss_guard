ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS input_tokens integer;
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS output_tokens integer;
ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS estimated_cost_usd numeric(10,6);