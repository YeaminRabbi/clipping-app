import { House, Radio, Scissors, Settings } from 'lucide-react'
import type { ReactNode } from 'react'
import { useApp } from '../store'

const ENGINE = {
  starting: { label: 'Engine starting', dot: 'bg-amber-400 animate-pulse', glow: '' },
  ready: { label: 'Engine ready', dot: 'bg-emerald-400', glow: 'shadow-[0_0_10px_#4ade80]' },
  error: { label: 'Engine error', dot: 'bg-red-500', glow: 'shadow-[0_0_10px_#ef4444]' },
  stopped: { label: 'Engine stopped', dot: 'bg-zinc-500', glow: '' }
} as const

function NavButton({ label, active, onClick, children }: { label: string; active: boolean; onClick(): void; children: ReactNode }) {
  return (
    <button
      onClick={onClick}
      aria-label={label}
      aria-current={active ? 'page' : undefined}
      title={label}
      className={`not-pill grid size-11 place-items-center rounded-full transition-colors ${
        active ? 'bg-white/12 text-white' : 'text-[#aeb9d1] hover:bg-white/10 hover:text-white'
      }`}
    >
      {children}
    </button>
  )
}

/** The floating glass rail on the left: logo, Home, engine status and Settings. */
export function Sidebar() {
  const settingsOpen = useApp((s) => s.settingsOpen)
  const liveOpen = useApp((s) => s.liveOpen)
  const recordingNow = useApp((s) => s.recordings.some((r) => r.status === 'recording' || r.status === 'reconnecting'))
  const engineState = useApp((s) => s.engine.state)
  const { goHome, openSettings, openLive } = useApp.getState()
  const engine = ENGINE[engineState]

  return (
    <nav
      aria-label="Main"
      className="glass-float fixed top-3.5 bottom-3.5 left-3.5 z-40 flex w-[68px] flex-col items-center gap-2 rounded-[24px] border bg-[rgba(255,255,255,0.04)] py-3.5 shadow-card"
    >
      <div className="mb-3 grid size-[42px] place-items-center rounded-full bg-accent text-on-accent" aria-hidden>
        <Scissors size={19} strokeWidth={1.8} />
      </div>
      <NavButton label="Projects" active={!settingsOpen && !liveOpen} onClick={goHome}>
        <House size={20} strokeWidth={1.6} aria-hidden />
      </NavButton>
      <NavButton label={recordingNow ? 'Live (recording now)' : 'Live'} active={liveOpen} onClick={openLive}>
        <span className="relative">
          <Radio size={20} strokeWidth={1.6} aria-hidden />
          {recordingNow && <span className="absolute -top-0.5 -right-1 size-2 animate-pulse rounded-full bg-red-500" aria-hidden />}
        </span>
      </NavButton>
      <div className="flex-1" />
      <NavButton label={`${engine.label}: open system check`} active={false} onClick={openSettings}>
        <span className={`size-2.5 rounded-full ${engine.dot} ${engine.glow}`} aria-hidden />
      </NavButton>
      <NavButton label="Settings" active={settingsOpen} onClick={openSettings}>
        <Settings size={20} strokeWidth={1.6} aria-hidden />
      </NavButton>
    </nav>
  )
}
