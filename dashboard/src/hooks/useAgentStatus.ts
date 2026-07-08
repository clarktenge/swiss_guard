import { useCallback, useEffect, useRef, useState } from 'react'
import { supabase, isSupabaseConfigured } from '@/lib/supabase'
import { AGENT_IDS } from '@/lib/agents'
import type {
  AgentOutput,
  AgentRun,
  AgentStatus,
  CharacterStatus,
  EvalResult,
} from '@/lib/types'

const POLL_MS = 60_000
const HOUR = 60 * 60 * 1000

/** Map a run + its age onto the character's visual state. */
function deriveStatus(run: AgentRun | null): CharacterStatus {
  if (!run) return 'sleeping'
  if (run.status === 'running') return 'running'
  if (run.status === 'error') return 'error'

  const ts = run.finished_at ?? run.started_at
  const age = Date.now() - new Date(ts).getTime()
  if (age <= 6 * HOUR) return 'success'
  if (age <= 24 * HOUR) return 'idle'
  return 'sleeping'
}

async function fetchAgent(agentId: string): Promise<AgentStatus> {
  // Last 7 runs (newest first) — powers the dot timeline and the latest-run card.
  const runsQ = supabase
    .from('agent_runs')
    .select(
      'id, agent_id, status, started_at, finished_at, latency_ms, error_message, eval_status, input_tokens, output_tokens, estimated_cost_usd',
    )
    .eq('agent_id', agentId)
    .order('started_at', { ascending: false })
    .limit(7)

  // Most recent output for this agent.
  const outputQ = supabase
    .from('agent_outputs')
    .select(
      'id, run_id, agent_id, content, governance_class, eval_passed, structured_output, created_at',
    )
    .eq('agent_id', agentId)
    .order('created_at', { ascending: false })
    .limit(1)

  const [runsRes, outputRes] = await Promise.all([runsQ, outputQ])

  if (runsRes.error) throw runsRes.error
  if (outputRes.error) throw outputRes.error

  const recentRuns = (runsRes.data ?? []) as AgentRun[]
  const latestRun = recentRuns[0] ?? null
  const latestOutput = (outputRes.data?.[0] ?? null) as AgentOutput | null

  // Eval results for whichever run is most relevant: the latest run, else the
  // run that produced the latest output.
  const evalRunId = latestRun?.id ?? latestOutput?.run_id ?? null
  let evalResults: EvalResult[] = []
  if (evalRunId) {
    const evalRes = await supabase
      .from('eval_results')
      .select('id, run_id, agent_id, check_name, tier, passed, score, reason, created_at')
      .eq('run_id', evalRunId)
      .order('tier', { ascending: true })
      .order('check_name', { ascending: true })
    if (evalRes.error) throw evalRes.error
    evalResults = (evalRes.data ?? []) as EvalResult[]
  }

  return {
    agentId,
    latestRun,
    latestOutput,
    recentRuns,
    evalResults,
    characterStatus: deriveStatus(latestRun),
  }
}

export interface UseAgentStatus {
  statuses: Record<string, AgentStatus>
  loading: boolean
  error: string | null
  lastRefreshed: Date | null
  configured: boolean
  refresh: () => void
}

/**
 * Fetches run/output/eval data for all six agents and re-polls every 60s.
 * Fails soft: on error it keeps the last good data and surfaces `error`.
 */
export function useAgentStatus(): UseAgentStatus {
  const [statuses, setStatuses] = useState<Record<string, AgentStatus>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null)
  const mounted = useRef(true)

  const load = useCallback(async () => {
    if (!isSupabaseConfigured) {
      setLoading(false)
      setError(
        'Supabase is not configured — copy .env.example to .env and set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY.',
      )
      return
    }
    try {
      const results = await Promise.all(AGENT_IDS.map(fetchAgent))
      if (!mounted.current) return
      const next: Record<string, AgentStatus> = {}
      for (const r of results) next[r.agentId] = r
      setStatuses(next)
      setError(null)
      setLastRefreshed(new Date())
    } catch (e) {
      if (!mounted.current) return
      setError(e instanceof Error ? e.message : 'Failed to load agent data')
    } finally {
      if (mounted.current) setLoading(false)
    }
  }, [])

  useEffect(() => {
    mounted.current = true
    load()
    const id = setInterval(load, POLL_MS)
    return () => {
      mounted.current = false
      clearInterval(id)
    }
  }, [load])

  return {
    statuses,
    loading,
    error,
    lastRefreshed,
    configured: isSupabaseConfigured,
    refresh: load,
  }
}
