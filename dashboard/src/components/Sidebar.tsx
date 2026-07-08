import { motion } from 'framer-motion'
import { PanelLeftClose, PanelLeftOpen } from 'lucide-react'
import { NAV_ITEMS, type ViewId } from '@/lib/nav'

interface SidebarProps {
  expanded: boolean
  onToggle: () => void
  active: ViewId
  onNavigate: (view: ViewId) => void
}

export function Sidebar({ expanded, onToggle, active, onNavigate }: SidebarProps) {
  return (
    <motion.nav
      animate={{ width: expanded ? 220 : 64 }}
      transition={{ type: 'spring', stiffness: 380, damping: 34 }}
      className="flex h-full shrink-0 flex-col border-r border-border bg-panel"
    >
      {/* logo mark */}
      <div className="flex h-16 items-center gap-3 px-4">
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-accent/15 text-xl">
          🛡️
        </span>
        {expanded && (
          <div className="overflow-hidden whitespace-nowrap">
            <div className="text-sm font-semibold text-gray-100">Swiss Guard</div>
            <div className="text-[10px] uppercase tracking-wider text-gray-500">
              agent control
            </div>
          </div>
        )}
      </div>

      {/* nav links */}
      <div className="mt-2 flex flex-1 flex-col gap-1 px-2.5">
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon
          const isActive = item.id === active
          return (
            <button
              key={item.id}
              onClick={() => onNavigate(item.id)}
              title={item.label}
              className={`flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm transition-colors ${
                isActive
                  ? 'bg-accent/15 text-accent'
                  : 'text-gray-400 hover:bg-border hover:text-gray-200'
              }`}
            >
              <Icon size={18} className="shrink-0" />
              {expanded && <span className="whitespace-nowrap">{item.label}</span>}
            </button>
          )
        })}
      </div>

      {/* collapse toggle */}
      <button
        onClick={onToggle}
        aria-label={expanded ? 'Collapse sidebar' : 'Expand sidebar'}
        className="m-2.5 flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm text-gray-500 transition-colors hover:bg-border hover:text-gray-200"
      >
        {expanded ? <PanelLeftClose size={18} /> : <PanelLeftOpen size={18} />}
        {expanded && <span>Collapse</span>}
      </button>
    </motion.nav>
  )
}
