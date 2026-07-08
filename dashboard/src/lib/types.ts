// Row shapes mirror db/schema.sql + migrations 001/005/006.
// Only the columns the dashboard reads are typed here.

export type RunStatus = 'running' | 'success' | 'error'
export type EvalStatus = 'pending' | 'passed' | 'failed' | 'skipped'

/** agent_runs — one row per agent firing. */
export interface AgentRun {
  id: string
  agent_id: string
  status: RunStatus
  started_at: string
  finished_at: string | null
  latency_ms: number | null
  error_message: string | null
  eval_status: EvalStatus | null
  input_tokens: number | null
  output_tokens: number | null
  estimated_cost_usd: number | null
}

/** agent_outputs — the content each agent produced. */
export interface AgentOutput {
  id: string
  run_id: string | null
  agent_id: string
  content: string
  governance_class: string | null
  eval_passed: boolean | null
  structured_output: Record<string, unknown> | null
  created_at: string
}

/** eval_results — one row per check per run. */
export interface EvalResult {
  id: string
  run_id: string
  agent_id: string
  check_name: string
  tier: number
  passed: boolean
  score: number | null
  reason: string | null
  created_at: string
}

/**
 * Character/UI state derived from the most recent run.
 *
 *  - success:  ran in the last 6h and status === 'success'
 *  - running:  most recent run still in progress
 *  - error:    most recent run status === 'error'
 *  - idle:     last success 6–24h ago
 *  - sleeping: 24h+ ago, or never ran
 */
export type CharacterStatus =
  | 'success'
  | 'running'
  | 'error'
  | 'idle'
  | 'sleeping'

/** Everything the apartment + panel need for one agent, assembled by the hook. */
export interface AgentStatus {
  agentId: string
  latestRun: AgentRun | null
  latestOutput: AgentOutput | null
  recentRuns: AgentRun[] // newest first, up to 7, for the dot timeline
  evalResults: EvalResult[] // checks from the latest run
  characterStatus: CharacterStatus
}
