import { Plus, Trash2 } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useApp } from '../store'
import { confirmAction } from '../lib/confirm'

export function Projects() {
  const ready = useApp((s) => s.engine.state === 'ready')
  const projects = useApp((s) => s.projects)
  const createProject = useApp((s) => s.createProject)
  const deleteProject = useApp((s) => s.deleteProject)
  const openProject = useApp((s) => s.openProject)
  const [name, setName] = useState('')

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return
    await createProject(name.trim())
    setName('')
  }

  return (
    <section className="flex flex-col rounded-xl border border-line bg-panel p-5">
      <h2 className="text-sm font-semibold">Projects</h2>
      <p className="mt-1 text-xs text-muted">Each project holds one or more source videos and the clips made from them.</p>

      <form onSubmit={submit} className="mt-4 flex gap-2">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="New project name"
          disabled={!ready}
          className="flex-1 rounded-md border border-line bg-panel-2 px-3 py-2 text-sm outline-none placeholder:text-muted focus:border-accent disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={!ready || !name.trim()}
          className="inline-flex items-center gap-1.5 rounded-md bg-accent px-4 py-2 text-sm font-medium hover:bg-accent-hover disabled:opacity-50"
        >
          <Plus size={16} aria-hidden />
          Create
        </button>
      </form>

      <ul className="mt-4 flex flex-col gap-2">
        {projects.length === 0 && (
          <li className="rounded-md border border-dashed border-line px-4 py-8 text-center text-sm text-muted">
            {ready ? 'No projects yet. Create one to get started.' : 'Waiting for the engine'}
          </li>
        )}
        {projects.map((p) => (
          <li key={p.id} className="flex items-center justify-between rounded-md border border-line bg-panel-2 hover:border-accent/60">
            <button onClick={() => void openProject(p.id)} className="min-w-0 flex-1 px-4 py-3 text-left">
              <div className="truncate text-sm font-medium">{p.name}</div>
              <div className="text-xs text-muted">
                {p.source_count} source{p.source_count === 1 ? '' : 's'} · created{' '}
                {new Date(p.created_at).toLocaleString()}
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
              className="mr-3 grid size-7 place-items-center rounded-md text-muted border border-transparent hover:border-danger-border hover:bg-red-950/60 hover:text-red-300"
            >
              <Trash2 size={14} aria-hidden />
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}
