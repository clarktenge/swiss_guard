import { useMemo, useState } from 'react'
import { AnimatePresence } from 'framer-motion'
import { AlertTriangle, RefreshCw } from 'lucide-react'
import { Sidebar } from './components/Sidebar'
import { ApartmentView } from './components/ApartmentView'
import { AgentPanel } from './components/AgentPanel'
import { PlaceholderPage } from './components/PlaceholderPage'
import { useAgentStatus } from './hooks/useAgentStatus'
import { AGENTS, agentById } from './lib/agents'
import { navById, type ViewId } from './lib/nav'
import { relativeTime } from './lib/format'
import type { CharacterStatus } from './lib/types'

function HomeHeader({
  statuses,
}: {
  statuses: Record<string, ReturnType<typeof useAgentStatus>['statuses'][string]>
}) {
  const counts = useMemo(() => {
    const c: Record<CharacterStatus, number> = {
      success: 0,
      running: 0,
      idle: 0,
      error: 0,
      sleeping: 0,
    }
    for (const a of AGENTS) {
      const cs = statuses[a.agentId]?.characterStatus ?? 'sleeping'
      c[cs] += 1
    }
    return c
  }, [statuses])

  const chips: { label: string; n: number; color: string }[] = [
    { label: 'healthy', n: counts.success, color: 'text-ok' },
    { label: 'running', n: counts.running, color: 'text-accent' },
    { label: 'idle', n: counts.idle, color: 'text-warn' },
    { label: 'error', n: counts.error, color: 'text-bad' },
    { label: 'asleep', n: counts.sleeping, color: 'text-gray-400' },
  ]

  return (
    <div className="flex items-center justify-between px-6 pb-1 pt-5">
      <div>
        <h1 className="text-lg font-semibold text-gray-100">The Apartment</h1>
        <p className="text-xs text-gray-500">Six agents, six rooms. Click a room for details.</p>
      </div>
      <div className="flex items-center gap-3 font-mono text-xs">
        {chips
          .filter((c) => c.n > 0)
          .map((c) => (
            <span key={c.label} className={c.color}>
              {c.n} {c.label}
            </span>
          ))}
      </div>
    </div>
  )
}

export default function App() {
  const [sidebarExpanded, setSidebarExpanded] = useState(false)
  const [view, setView] = useState<ViewId>('home')
  const [selectedAgentId, setSelectedAgentId] = useState<string | null>(null)

  const { statuses, loading, error, lastRefreshed, configured, refresh } = useAgentStatus()

  const selectedAgent = selectedAgentId ? agentById(selectedAgentId) : undefined
  const panelOpen = view === 'home' && !!selectedAgent

  const handleNavigate = (next: ViewId) => {
    setView(next)
    if (next !== 'home') setSelectedAgentId(null)
  }

  const handleSelectRoom = (agentId: string) => {
    setSelectedAgentId((cur) => (cur === agentId ? null : agentId))
  }

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-bg text-gray-200">
      <Sidebar
        expanded={sidebarExpanded}
        onToggle={() => setSidebarExpanded((e) => !e)}
        active={view}
        onNavigate={handleNavigate}
      />

      {/* main area */}
      <main className="flex min-w-0 flex-1 flex-col">
        {view === 'home' ? (
          <div className="flex min-h-0 flex-1">
            {/* apartment column */}
            <section className="flex min-w-0 flex-1 flex-col">
              <HomeHeader statuses={statuses} />

              {/* config / error banners */}
              {!configured && (
                <div className="mx-6 mb-1 mt-2 rounded-lg border border-warn/30 bg-warn/10 px-4 py-2.5 text-xs text-amber-200">
                  Supabase isn’t configured — copy{' '}
                  <code className="font-mono">.env.example</code> to{' '}
                  <code className="font-mono">.env</code> and set your URL + anon key. The
                  apartment renders with everyone asleep until then.
                </div>
              )}
              {configured && error && (
                <div className="mx-6 mb-1 mt-2 flex items-center gap-2 rounded-lg border border-bad/30 bg-bad/10 px-4 py-2.5 text-xs text-red-200">
                  <AlertTriangle size={14} /> {error}
                </div>
              )}

              <div className="grid min-h-0 flex-1 place-items-center p-6">
                <div className="aspect-[900/720] w-full max-w-[960px]">
                  <ApartmentView
                    statuses={statuses}
                    selectedAgentId={selectedAgentId}
                    onSelectRoom={handleSelectRoom}
                  />
                </div>
              </div>

              {/* last-refreshed footer */}
              <div className="flex items-center justify-end gap-2 px-6 pb-3 font-mono text-[11px] text-gray-500">
                <button
                  onClick={refresh}
                  className="flex items-center gap-1.5 rounded-md px-2 py-1 transition-colors hover:bg-border hover:text-gray-300"
                  title="Refresh now"
                >
                  <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
                  {loading
                    ? 'refreshing…'
                    : lastRefreshed
                      ? `updated ${relativeTime(lastRefreshed.toISOString())}`
                      : 'not yet loaded'}
                </button>
                <span className="text-gray-600">· polls every 60s</span>
              </div>
            </section>

            {/* right panel */}
            <AnimatePresence mode="wait">
              {panelOpen && selectedAgent && (
                <AgentPanel
                  agent={selectedAgent}
                  status={statuses[selectedAgent.agentId]}
                  onClose={() => setSelectedAgentId(null)}
                />
              )}
            </AnimatePresence>
          </div>
        ) : (
          <PlaceholderPage
            title={navById(view).label}
            blurb={navById(view).blurb}
            icon={navById(view).icon}
          />
        )}
      </main>
    </div>
  )
}
