import { AnimatePresence, motion } from 'framer-motion'
import { X, CheckCircle2, XCircle, CircleDot, Clock } from 'lucide-react'
import type { AgentMeta } from '@/lib/agents'
import type { AgentStatus, CharacterStatus, RunStatus } from '@/lib/types'
import { MarkdownLite } from './MarkdownLite'
import {
  absoluteTime,
  duration,
  formatCost,
  formatTokens,
  relativeTime,
} from '@/lib/format'

interface AgentPanelProps {
  agent: AgentMeta
  status: AgentStatus | undefined
  onClose: () => void
}

const STATUS_LABEL: Record<CharacterStatus, string> = {
  success: 'Healthy',
  running: 'Running',
  idle: 'Idle',
  error: 'Error',
  sleeping: 'Asleep',
}

function statusBadgeClasses(cs: CharacterStatus): string {
  switch (cs) {
    case 'success':
      return 'bg-ok/15 text-ok border-ok/30'
    case 'running':
      return 'bg-accent/15 text-accent border-accent/30'
    case 'idle':
      return 'bg-warn/15 text-warn border-warn/30'
    case 'error':
      return 'bg-bad/15 text-bad border-bad/30'
    case 'sleeping':
    default:
      return 'bg-muted/15 text-gray-400 border-muted/30'
  }
}

function runDotColor(s: RunStatus): string {
  if (s === 'success') return 'bg-ok'
  if (s === 'error') return 'bg-bad'
  return 'bg-accent'
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="border-t border-border px-5 py-4">
      <div className="mb-2.5 text-[11px] font-semibold uppercase tracking-wider text-gray-500">
        {title}
      </div>
      {children}
    </div>
  )
}

export function AgentPanel({ agent, status, onClose }: AgentPanelProps) {
  const cs = status?.characterStatus ?? 'sleeping'
  const run = status?.latestRun ?? null
  const output = status?.latestOutput ?? null
  const evals = status?.evalResults ?? []
  const recent = status?.recentRuns ?? []

  return (
    <AnimatePresence>
      <motion.aside
        key={agent.agentId}
        initial={{ x: 40, opacity: 0 }}
        animate={{ x: 0, opacity: 1 }}
        exit={{ x: 40, opacity: 0 }}
        transition={{ type: 'spring', stiffness: 320, damping: 32 }}
        className="flex h-full w-[380px] shrink-0 flex-col overflow-y-auto border-l border-border bg-panel"
      >
        {/* header */}
        <div className="flex items-start justify-between px-5 pb-4 pt-5">
          <div className="pr-3">
            <div className="flex items-center gap-2">
              <span
                className="h-2.5 w-2.5 rounded-full"
                style={{ background: agent.ambient }}
              />
              <h2 className="text-lg font-semibold text-gray-100">{agent.name}</h2>
            </div>
            <p className="mt-1.5 text-[12.5px] leading-relaxed text-gray-400">
              {agent.description}
            </p>
          </div>
          <button
            onClick={onClose}
            aria-label="Close panel"
            className="rounded-md p-1.5 text-gray-500 transition-colors hover:bg-border hover:text-gray-200"
          >
            <X size={18} />
          </button>
        </div>

        {/* last run */}
        <Section title="Last Run">
          <div className="flex items-center justify-between">
            <span
              className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium ${statusBadgeClasses(
                cs,
              )}`}
            >
              {cs === 'error' ? (
                <XCircle size={13} />
              ) : cs === 'success' ? (
                <CheckCircle2 size={13} />
              ) : (
                <CircleDot size={13} />
              )}
              {STATUS_LABEL[cs]}
            </span>
            <span className="flex items-center gap-1.5 font-mono text-xs text-gray-400">
              <Clock size={12} /> {relativeTime(run?.started_at)}
            </span>
          </div>
          <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
            <div>
              <dt className="text-gray-500">Started</dt>
              <dd className="mt-0.5 font-mono text-gray-300">{absoluteTime(run?.started_at)}</dd>
            </div>
            <div>
              <dt className="text-gray-500">Duration</dt>
              <dd className="mt-0.5 font-mono text-gray-300">{duration(run?.latency_ms)}</dd>
            </div>
            <div>
              <dt className="text-gray-500">Eval</dt>
              <dd className="mt-0.5 font-mono text-gray-300">{run?.eval_status ?? '—'}</dd>
            </div>
            <div>
              <dt className="text-gray-500">Governance</dt>
              <dd className="mt-0.5 font-mono text-gray-300">
                {output?.governance_class ?? '—'}
              </dd>
            </div>
          </dl>
          {run?.error_message && (
            <p className="mt-3 rounded-md border border-bad/30 bg-bad/10 px-3 py-2 font-mono text-[11px] leading-relaxed text-red-300">
              {run.error_message}
            </p>
          )}
        </Section>

        {/* 7-run timeline */}
        <Section title="Last 7 Runs">
          {recent.length === 0 ? (
            <p className="text-xs text-gray-500">No runs recorded yet.</p>
          ) : (
            <div className="flex items-center gap-2">
              {[...recent].reverse().map((r) => (
                <div key={r.id} className="group relative">
                  <span
                    className={`block h-3.5 w-3.5 rounded-full ${runDotColor(r.status)} ${
                      r.status === 'running' ? 'animate-pulse' : ''
                    }`}
                    title={`${r.status} · ${relativeTime(r.started_at)}`}
                  />
                </div>
              ))}
              <span className="ml-1 font-mono text-[11px] text-gray-500">
                {recent[0] ? relativeTime(recent[0].started_at) : ''}
              </span>
            </div>
          )}
        </Section>

        {/* token cost */}
        <Section title="Cost (latest run)">
          <div className="grid grid-cols-3 gap-2">
            {[
              ['Input', formatTokens(run?.input_tokens)],
              ['Output', formatTokens(run?.output_tokens)],
              ['Est. cost', formatCost(run?.estimated_cost_usd)],
            ].map(([label, value]) => (
              <div key={label} className="rounded-md border border-border bg-[#0f1117] px-2.5 py-2">
                <div className="text-[10px] uppercase tracking-wide text-gray-500">{label}</div>
                <div className="mt-0.5 font-mono text-sm text-gray-200">{value}</div>
              </div>
            ))}
          </div>
        </Section>

        {/* eval results */}
        <Section title="Eval Checks">
          {evals.length === 0 ? (
            <p className="text-xs text-gray-500">No eval results for the latest run.</p>
          ) : (
            <div className="space-y-2">
              {evals.map((e) => (
                <div
                  key={e.id}
                  className={`rounded-md border px-3 py-2 ${
                    e.passed ? 'border-ok/25 bg-ok/5' : 'border-bad/30 bg-bad/10'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="flex items-center gap-1.5 font-mono text-xs text-gray-200">
                      {e.passed ? (
                        <CheckCircle2 size={13} className="text-ok" />
                      ) : (
                        <XCircle size={13} className="text-bad" />
                      )}
                      {e.check_name}
                    </span>
                    <span className="text-[10px] uppercase tracking-wide text-gray-500">
                      tier {e.tier}
                      {e.score != null ? ` · ${e.score.toFixed(2)}` : ''}
                    </span>
                  </div>
                  {e.reason && (
                    <p className="mt-1 text-[11.5px] leading-relaxed text-gray-400">{e.reason}</p>
                  )}
                </div>
              ))}
            </div>
          )}
        </Section>

        {/* latest output */}
        <Section title="Latest Output">
          {output?.content ? (
            <MarkdownLite content={output.content} />
          ) : (
            <p className="text-xs text-gray-500">No output stored yet.</p>
          )}
        </Section>

        <div className="mt-auto px-5 py-4 text-center font-mono text-[10px] text-gray-600">
          agent_id: {agent.agentId}
        </div>
      </motion.aside>
    </AnimatePresence>
  )
}
