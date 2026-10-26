import { useEffect } from 'react'
import { useApp } from './store'
import { EngineBadge } from './components/EngineBadge'
import { SystemCheck } from './components/SystemCheck'
import { Projects } from './components/Projects'

export default function App() {
  const init = useApp((s) => s.init)
  const error = useApp((s) => s.error)

  useEffect(() => init(), [init])

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center justify-between border-b border-line bg-panel px-6 py-3">
        <div className="flex items-center gap-3">
          <div className="grid size-8 place-items-center rounded-lg bg-accent text-sm font-bold">C</div>
          <h1 className="text-base font-semibold">Clipping App</h1>
        </div>
        <EngineBadge />
      </header>

      {error && (
        <div className="border-b border-red-900/60 bg-red-950/50 px-6 py-2 text-sm text-red-300">{error}</div>
      )}

      <main className="grid flex-1 grid-cols-1 gap-6 overflow-auto p-6 lg:grid-cols-[1fr_360px]">
        <Projects />
        <SystemCheck />
      </main>
    </div>
  )
}
