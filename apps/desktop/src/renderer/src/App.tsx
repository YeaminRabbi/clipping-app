import { CircleAlert, X } from 'lucide-react'
import { useEffect, useState, type DragEvent } from 'react'
import { useApp } from './store'
import { Sidebar } from './components/Sidebar'
import { UpdateBanner } from './components/UpdateBanner'
import { Projects } from './components/Projects'
import { ProjectView } from './components/ProjectView'
import { SettingsView } from './components/SettingsView'
import { NewProjectDialog } from './components/NewProjectDialog'
import { EditorView } from './components/editor/EditorView'
import { ExportDialog } from './components/ExportDialog'
import { AutoClipDialog } from './components/AutoClipDialog'
import { ConfirmDialogHost } from './components/ConfirmDialog'

export default function App() {
  const init = useApp((s) => s.init)
  const error = useApp((s) => s.error)
  const setError = useApp((s) => s.setError)
  const ready = useApp((s) => s.engine.state === 'ready')
  const settingsOpen = useApp((s) => s.settingsOpen)
  const projectOpen = useApp((s) => s.openProjectId !== null)
  const editorOpen = useApp((s) => s.editorSourceId !== null)
  const exportDialogOpen = useApp((s) => s.exportDialog !== null)
  const autoClipOpen = useApp((s) => s.autoClipDialog !== null)
  // New project dialog: null when closed, otherwise the files it starts with (dropped or none).
  const [newProject, setNewProject] = useState<string[] | null>(null)

  useEffect(() => init(), [init])

  const onHome = !settingsOpen && !projectOpen

  // On the projects home, a video dropped anywhere starts a new project with it.
  const onDragOver = (e: DragEvent) => {
    if (onHome && e.dataTransfer.types.includes('Files')) e.preventDefault()
  }
  const onDrop = (e: DragEvent) => {
    if (!onHome) return
    e.preventDefault()
    if (!ready) return
    const paths = [...e.dataTransfer.files].map((f) => window.clipping.files.pathFor(f)).filter(Boolean)
    if (paths.length) setNewProject(paths)
  }

  const view = settingsOpen ? (
    <main className="min-h-0 flex-1 overflow-auto">
      <SettingsView />
    </main>
  ) : editorOpen ? (
    <main className="min-h-0 flex-1">
      <EditorView />
    </main>
  ) : projectOpen ? (
    <main className="min-h-0 flex-1 overflow-auto">
      <ProjectView />
    </main>
  ) : (
    <main className="min-h-0 flex-1 overflow-auto">
      <Projects onNewProject={() => setNewProject([])} />
    </main>
  )

  return (
    <div className="h-full" onDragOver={onDragOver} onDrop={onDrop}>
      <Sidebar />
      <div className="flex h-full flex-col pl-[96px]">
        <UpdateBanner />

        {error && (
          <div role="alert" className="mx-4 mt-3.5 flex items-start justify-between gap-4 rounded-2xl border border-danger-border bg-danger-subtle px-4 py-2 text-sm text-red-300">
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

        {view}
      </div>

      {newProject !== null && <NewProjectDialog initialPaths={newProject} onClose={() => setNewProject(null)} />}
      {exportDialogOpen && <ExportDialog />}
      {autoClipOpen && <AutoClipDialog />}
      <ConfirmDialogHost />
    </div>
  )
}
