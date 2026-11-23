import { CircleAlert, Scissors, X } from 'lucide-react'
import { useEffect } from 'react'
import { useApp } from './store'
import { EngineBadge } from './components/EngineBadge'
import { UpdateBanner } from './components/UpdateBanner'
import { SystemCheck } from './components/SystemCheck'
import { Projects } from './components/Projects'
import { ProjectView } from './components/ProjectView'
import { EditorView } from './components/editor/EditorView'
import { ExportDialog } from './components/ExportDialog'
import { AutoClipDialog } from './components/AutoClipDialog'
import { ConfirmDialogHost } from './components/ConfirmDialog'

export default function App() {
  const init = useApp((s) => s.init)
  const error = useApp((s) => s.error)
  const setError = useApp((s) => s.setError)
  const projectOpen = useApp((s) => s.openProjectId !== null)
  const editorOpen = useApp((s) => s.editorSourceId !== null)
  const exportDialogOpen = useApp((s) => s.exportDialog !== null)
  const autoClipOpen = useApp((s) => s.autoClipDialog !== null)

  useEffect(() => init(), [init])

  return (
    <div className="flex h-full flex-col">
      <header className="flex items-center justify-between border-b border-line bg-panel px-6 py-3">
        <div className="flex items-center gap-3">
          <div className="grid size-8 place-items-center rounded-lg bg-accent">
            <Scissors size={16} aria-hidden />
          </div>
          <h1 className="text-base font-semibold">Clipping App</h1>
        </div>
        <div className="flex items-center gap-3">
          <UpdateBanner />
          <EngineBadge />
        </div>
      </header>

      {error && (
        <div role="alert" className="flex items-start justify-between gap-4 border-b border-red-900/60 bg-red-950/50 px-6 py-2 text-sm text-red-300">
          <span className="flex min-w-0 items-start gap-2 break-words">
            <CircleAlert size={16} aria-hidden className="mt-0.5 shrink-0" />
            {error}
          </span>
          <button
            onClick={() => setError(null)}
            className="inline-flex shrink-0 items-center gap-1 text-xs text-red-300/80 hover:text-red-200"
          >
            <X size={14} aria-hidden />
            Dismiss
          </button>
        </div>
      )}

      {editorOpen ? (
        <main className="min-h-0 flex-1">
          <EditorView />
        </main>
      ) : projectOpen ? (
        <main className="flex-1 overflow-auto">
          <ProjectView />
        </main>
      ) : (
        <main className="grid flex-1 grid-cols-1 gap-6 overflow-auto p-6 lg:grid-cols-[1fr_360px]">
          <Projects />
          <SystemCheck />
        </main>
      )}

      {exportDialogOpen && <ExportDialog />}
      {autoClipOpen && <AutoClipDialog />}
      <ConfirmDialogHost />
    </div>
  )
}
