import { useApp } from '../store'

const LABELS = {
  starting: { text: 'Engine starting…', dot: 'bg-amber-400 animate-pulse' },
  ready: { text: 'Engine ready', dot: 'bg-emerald-400' },
  error: { text: 'Engine error', dot: 'bg-red-500' },
  stopped: { text: 'Engine stopped', dot: 'bg-zinc-500' }
} as const

export function EngineBadge() {
  const state = useApp((s) => s.engine.state)
  const { text, dot } = LABELS[state]
  return (
    <div className="flex items-center gap-2 rounded-full border border-line bg-panel-2 px-3 py-1 text-xs text-muted">
      <span className={`size-2 rounded-full ${dot}`} />
      {text}
    </div>
  )
}
