import { useState, type DragEvent, type FormEvent } from 'react'
import { useApp } from '../store'

export function ImportPanel() {
  const ready = useApp((s) => s.engine.state === 'ready')
  const addUrl = useApp((s) => s.addUrl)
  const addFiles = useApp((s) => s.addFiles)
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState(false)
  const [dragging, setDragging] = useState(false)

  const submitUrl = async (e: FormEvent) => {
    e.preventDefault()
    const value = url.trim()
    if (!value) return
    setBusy(true)
    if (await addUrl(value)) setUrl('')
    setBusy(false)
  }

  const browse = async () => {
    const paths = await window.clipping.files.pickVideos()
    if (paths.length) await addFiles(paths)
  }

  const onDrop = async (e: DragEvent) => {
    e.preventDefault()
    setDragging(false)
    if (!ready) return
    const paths = [...e.dataTransfer.files].map((f) => window.clipping.files.pathFor(f)).filter(Boolean)
    if (paths.length) return addFiles(paths)
    // A link dragged from a browser arrives as text rather than a file.
    const link = (e.dataTransfer.getData('text/uri-list') || e.dataTransfer.getData('text/plain')).split(/\r?\n/)[0]
    if (/^https?:\/\//.test(link)) await addUrl(link.trim())
  }

  return (
    <section
      onDragOver={(e) => {
        e.preventDefault()
        setDragging(true)
      }}
      onDragLeave={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragging(false)
      }}
      onDrop={onDrop}
      className={`rounded-xl border bg-panel p-5 transition-colors ${dragging ? 'border-accent bg-accent/10' : 'border-line'}`}
    >
      <h2 className="text-sm font-semibold">Import a video</h2>
      <p className="mt-1 text-xs text-muted">
        Paste a link (YouTube, Vimeo, X, a direct .mp4 link…) or choose files from your computer. You can also drop
        files or links here.
      </p>

      <form onSubmit={submitUrl} className="mt-4 flex gap-2">
        <input
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          placeholder="https://…"
          disabled={!ready || busy}
          className="flex-1 rounded-md border border-line bg-panel-2 px-3 py-2 text-sm outline-none placeholder:text-muted focus:border-accent disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={!ready || busy || !url.trim()}
          className="rounded-md bg-accent px-4 py-2 text-sm font-medium hover:bg-accent-hover disabled:opacity-50"
        >
          Import link
        </button>
        <span className="self-center px-1 text-xs text-muted">or</span>
        <button
          type="button"
          onClick={() => void browse()}
          disabled={!ready}
          className="rounded-md border border-line px-4 py-2 text-sm font-medium hover:bg-panel-2 disabled:opacity-50"
        >
          Choose files…
        </button>
      </form>
      <p className="mt-3 text-[11px] text-muted">
        Only import videos you own or have permission to use. Local files are used where they are and are never
        modified.
      </p>
    </section>
  )
}
