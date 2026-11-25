import { Film, Plus, Trash2 } from 'lucide-react'
import { useApp } from '../store'
import { confirmAction } from '../lib/confirm'

/** The projects home: a card per project and the New project button. */
export function Projects({ onNewProject }: { onNewProject(): void }) {
  const ready = useApp((s) => s.engine.state === 'ready')
  const projects = useApp((s) => s.projects)
  const deleteProject = useApp((s) => s.deleteProject)
  const openProject = useApp((s) => s.openProject)

  return (
    <div className="flex flex-col gap-6 px-8 py-7">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-semibold tracking-[-0.02em]">Projects</h1>
          <p className="mt-1 text-sm text-muted">
            Each project holds your videos and the clips found in them. Drop a video anywhere to start a new one.
          </p>
        </div>
        <button
          onClick={onNewProject}
          disabled={!ready}
          className="inline-flex h-11 items-center gap-2 rounded-full bg-accent px-5 text-sm font-semibold text-on-accent hover:bg-accent-hover disabled:opacity-50"
        >
          <Plus size={16} strokeWidth={2} aria-hidden />
          New project
        </button>
      </div>

      {projects.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-white/20 px-6 py-16 text-center text-sm text-muted">
          {ready ? 'No projects yet. Click New project or drop a video here to get started.' : 'Waiting for the engine'}
        </div>
      ) : (
        <ul className="grid grid-cols-[repeat(auto-fill,minmax(260px,1fr))] gap-4">
          {projects.map((p) => (
            <li key={p.id} className="group relative flex flex-col rounded-2xl border border-line bg-panel p-2 shadow-card hover:border-white/25">
              <button onClick={() => void openProject(p.id)} className="not-pill flex flex-col rounded-xl text-left">
                <div className="grid h-28 place-items-center rounded-xl bg-[#15233f] text-[#6f7d99]">
                  <Film size={28} strokeWidth={1.4} aria-hidden />
                </div>
                <div className="px-2 pt-3 pb-1.5">
                  <div className="truncate text-sm font-semibold">{p.name}</div>
                  <div className="mt-0.5 text-xs text-muted">
                    {p.source_count} video{p.source_count === 1 ? '' : 's'} · created {new Date(p.created_at).toLocaleDateString()}
                  </div>
                </div>
              </button>
              <button
                onClick={async () => {
                  const ok = await confirmAction({
                    title: `Delete "${p.name}"?`,
                    message: 'Its videos, clips and export history are removed, and videos it downloaded from links are deleted. Files you imported from your computer and videos you exported are kept.',
                    confirmLabel: 'Delete project',
                    danger: true
                  })
                  if (ok) void deleteProject(p.id)
                }}
                aria-label={`Delete project ${p.name}`}
                title="Delete project"
                className="not-pill absolute top-4 right-4 grid size-8 place-items-center rounded-full bg-[rgba(10,17,32,0.7)] text-muted opacity-0 group-hover:opacity-100 focus-visible:opacity-100 hover:bg-red-950/80 hover:text-red-300"
              >
                <Trash2 size={14} aria-hidden />
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
