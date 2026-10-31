import { useApp } from '../store'
import { ExportsPanel } from './ExportsPanel'
import { ImportPanel } from './ImportPanel'
import { SourceCard } from './SourceCard'

export function ProjectView() {
  const project = useApp((s) => s.projects.find((p) => p.id === s.openProjectId))
  const sources = useApp((s) => s.sources)
  const clips = useApp((s) => s.clips)
  const { closeProject, openExportDialog } = useApp.getState()

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 p-6">
      <div className="flex items-center gap-3">
        <button onClick={closeProject} className="rounded-md border border-line px-2.5 py-1 text-xs text-muted hover:bg-panel-2">
          ← Projects
        </button>
        <h2 className="min-w-0 flex-1 truncate text-lg font-semibold">{project?.name ?? 'Project'}</h2>
        <button
          onClick={() => openExportDialog(clips.map((c) => c.id))}
          disabled={clips.length === 0}
          title={clips.length === 0 ? 'Open a video and make some clips first' : undefined}
          className="rounded-md bg-accent px-4 py-2 text-sm font-medium hover:bg-accent-hover disabled:opacity-50"
        >
          Export {clips.length > 0 ? `${clips.length} clip${clips.length === 1 ? '' : 's'}` : 'clips'}…
        </button>
      </div>

      <ImportPanel />

      <section className="rounded-xl border border-line bg-panel p-5">
        <h2 className="text-sm font-semibold">
          Sources <span className="font-normal text-muted">({sources.length})</span>
        </h2>
        <ul className="mt-4 flex flex-col gap-3">
          {sources.length === 0 && (
            <li className="rounded-md border border-dashed border-line px-4 py-10 text-center text-sm text-muted">
              No videos yet. Import a link or a file above.
            </li>
          )}
          {sources.map((source) => (
            <SourceCard key={source.id} source={source} clipCount={clips.filter((c) => c.source_id === source.id).length} />
          ))}
        </ul>
      </section>

      <ExportsPanel />
    </div>
  )
}
