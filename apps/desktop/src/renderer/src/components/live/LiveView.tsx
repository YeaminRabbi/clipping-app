import { Check, CircleAlert, Flag, FolderOpen, LoaderCircle, Radio, Square, Trash2 } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'
import { useApp } from '../../store'
import { RECORDING_ACTIVE, type Recording, type RecordingQuality } from '../../lib/api'
import { describePrefs, loadPrefs, paramsFromPrefs } from '../../lib/autoClipPrefs'
import { displayedExportBase } from '../../lib/exportFolder'
import { confirmAction } from '../../lib/confirm'
import { LivePlayer } from './LivePlayer'
import { Select } from '../Select'

const QUALITIES: { key: RecordingQuality; label: string }[] = [
  { key: 'source', label: 'Source' },
  { key: '1080', label: '1080p' },
  { key: '720', label: '720p' }
]
const NEW_PROJECT = -1
const AUTO_KEY = 'clipping.liveAutoClip'
const LAST_PROJECT_KEY = 'clipping.liveProject'

const clock = (ms: number): string => {
  const s = Math.floor(ms / 1000)
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  return `${h}:${String(m).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
}
const gb = (bytes: number): string => `${(bytes / 1024 ** 3).toFixed(bytes >= 10 * 1024 ** 3 ? 0 : 1)} GB`

const STATUS_TEXT: Record<Recording['status'], string> = {
  starting: 'Connecting',
  recording: 'Recording',
  reconnecting: 'Reconnecting',
  finishing: 'Saving',
  done: 'Saved',
  failed: 'Failed',
  cancelled: 'Stopped before anything was recorded',
  interrupted: 'Interrupted'
}

function readFlag(key: string, fallback: boolean): boolean {
  try {
    const v = localStorage.getItem(key)
    return v === null ? fallback : v === 'true'
  } catch {
    return fallback
  }
}

function StartPanel() {
  const ready = useApp((s) => s.engine.state === 'ready')
  const projects = useApp((s) => s.projects)
  const { startRecording, createProject } = useApp.getState()
  const [url, setUrl] = useState('')
  const [projectId, setProjectId] = useState<number>(() => {
    try {
      return Number(localStorage.getItem(LAST_PROJECT_KEY)) || NEW_PROJECT
    } catch {
      return NEW_PROJECT
    }
  })
  const [quality, setQuality] = useState<RecordingQuality>('source')
  const [autoClip, setAutoClip] = useState(() => readFlag(AUTO_KEY, true))
  const [folder, setFolder] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const prefs = loadPrefs()

  useEffect(() => {
    void displayedExportBase().then((base) => setFolder(`${base}${base.includes('\\') ? '\\' : '/'}Recordings`))
  }, [])

  // A remembered project that has since been deleted falls back to "new project".
  const chosen = projects.some((p) => p.id === projectId) ? projectId : NEW_PROJECT

  const start = async () => {
    const link = url.trim()
    if (!link || !folder || busy) return
    setBusy(true)
    try {
      localStorage.setItem(AUTO_KEY, String(autoClip))
    } catch {
      // Remembering the choice is a convenience only.
    }
    let target = chosen
    if (target === NEW_PROJECT) {
      const project = await createProject(`Live recordings ${new Date().toLocaleDateString()}`)
      if (!project) {
        setBusy(false)
        return
      }
      target = project.id
    }
    try {
      localStorage.setItem(LAST_PROJECT_KEY, String(target))
    } catch {
      // As above.
    }
    const rec = await startRecording(link, target, quality, folder, autoClip ? paramsFromPrefs(prefs) : null)
    setBusy(false)
    if (rec) setUrl('')
  }

  return (
    <section className="flex flex-col gap-4 rounded-2xl border border-line bg-panel p-5 shadow-card">
      <div>
        <h2 className="text-[15px] font-semibold">Record a live stream</h2>
        <p className="mt-1 text-xs text-muted">
          Paste the link of a Twitch or YouTube stream that's live now. Only record streams you own or have permission to use.
        </p>
      </div>
      <div className="flex flex-wrap gap-2">
        <label htmlFor="live-url" className="sr-only">
          Live stream link
        </label>
        <input
          id="live-url"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && void start()}
          placeholder="https://twitch.tv/yourchannel or a YouTube live link"
          className="h-11 min-w-0 flex-[1_1_320px] rounded-full border border-white/15 bg-[rgba(6,12,26,0.45)] px-4 text-sm outline-none placeholder:text-[#8794b0] focus:border-white/40"
        />
        <button
          onClick={() => void start()}
          disabled={!ready || busy || !url.trim() || !folder}
          className="inline-flex h-11 items-center gap-2 rounded-full bg-accent px-5 text-sm font-semibold text-on-accent hover:bg-accent-hover disabled:opacity-40"
        >
          {busy ? <LoaderCircle size={16} className="animate-spin" aria-hidden /> : <span className="size-2.5 rounded-full bg-red-500" aria-hidden />}
          Start recording
        </button>
      </div>
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3 text-xs">
        <label className="flex items-center gap-2 text-muted">
          Save into
          <Select<number>
            value={chosen}
            onChange={setProjectId}
            aria-label="Project to save the recording into"
            className="h-9 min-w-[170px] rounded-full border border-white/15 bg-[rgba(6,12,26,0.6)] px-3.5 text-xs text-ink"
            options={[{ value: NEW_PROJECT, label: 'A new project' }, ...projects.map((p) => ({ value: p.id, label: p.name }))]}
          />
        </label>
        <div role="radiogroup" aria-label="Quality" className="flex items-center gap-1 rounded-full bg-white/[0.07] p-1">
          {QUALITIES.map((q) => (
            <button
              key={q.key}
              role="radio"
              aria-checked={quality === q.key}
              onClick={() => setQuality(q.key)}
              className={`not-pill h-7 rounded-full px-3 font-medium ${quality === q.key ? 'bg-accent text-on-accent' : 'text-[#c8d1e4] hover:bg-white/10'}`}
            >
              {q.label}
            </button>
          ))}
        </div>
        <button
          role="checkbox"
          aria-checked={autoClip}
          onClick={() => setAutoClip(!autoClip)}
          title={`Uses your last Find clips settings: ${describePrefs(prefs)}`}
          className="not-pill inline-flex items-center gap-2 text-left"
        >
          <span className={`grid size-5 place-items-center rounded-full border-[1.5px] ${autoClip ? 'border-accent bg-accent text-on-accent' : 'border-[#7b88a6]'}`}>
            {autoClip && <Check size={11} strokeWidth={3} aria-hidden />}
          </span>
          Find clips when the stream ends
        </button>
      </div>
      {folder && (
        <p className="text-[11px] text-muted">
          Recordings are saved to <span className="text-[#c8d1e4]">{folder}</span>. Change the location in Settings, under Exports.
        </p>
      )}
    </section>
  )
}

function ActiveRecording({ rec }: { rec: Recording }) {
  const client = useApp((s) => s.client)
  const { markRecording, stopRecording, discardRecording } = useApp.getState()
  const recording = rec.status === 'recording' || rec.status === 'reconnecting'
  const lowDisk = rec.free_bytes !== null && rec.free_bytes < 10 * 1024 ** 3

  // M marks a moment while this recording is on screen (not while typing in a field).
  useEffect(() => {
    if (!recording) return
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null
      if (e.key.toLowerCase() !== 'm' || e.ctrlKey || e.metaKey || e.altKey) return
      if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT' || target.isContentEditable)) return
      e.preventDefault()
      void markRecording(rec.id)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [recording, rec.id, markRecording])

  return (
    <section className="flex flex-col gap-3 rounded-2xl border border-line bg-panel p-4 shadow-card">
      {client && <LivePlayer client={client} previewUrl={rec.preview_url} />}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            {rec.status === 'recording' ? (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-red-600 px-2.5 py-0.5 text-[11px] font-bold text-white">
                <span className="size-1.5 animate-pulse rounded-full bg-white" aria-hidden />
                REC
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-warning-subtle px-2.5 py-0.5 text-[11px] font-semibold text-amber-300">
                <LoaderCircle size={11} className="animate-spin" aria-hidden />
                {STATUS_TEXT[rec.status]}
              </span>
            )}
            <span className="truncate text-sm font-semibold">{rec.channel ?? rec.url}</span>
          </div>
          {rec.title && <div className="mt-0.5 truncate text-xs text-muted">{rec.title}</div>}
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => void markRecording(rec.id)}
            disabled={!recording}
            title="Mark what's happening now (M). Each mark becomes a clip after the recording is saved."
            className="inline-flex h-10 items-center gap-2 rounded-full border border-white/20 px-4 text-sm hover:bg-white/10 disabled:opacity-40"
          >
            <Flag size={15} aria-hidden />
            Mark moment
            <kbd className="rounded bg-white/10 px-1.5 text-[10px] text-muted">M</kbd>
          </button>
          <button
            onClick={() => void stopRecording(rec.id)}
            disabled={rec.status === 'finishing'}
            className="inline-flex h-10 items-center gap-2 rounded-full bg-accent px-4 text-sm font-semibold text-on-accent hover:bg-accent-hover disabled:opacity-40"
          >
            <Square size={13} fill="currentColor" aria-hidden />
            Stop and save
          </button>
          <button
            onClick={async () => {
              const ok = await confirmAction({
                title: 'Discard this recording?',
                message: 'The recording stops and everything recorded so far is deleted.',
                confirmLabel: 'Discard',
                danger: true
              })
              if (ok) void discardRecording(rec.id)
            }}
            disabled={rec.status === 'finishing'}
            aria-label="Discard recording"
            title="Discard"
            className="not-pill grid size-10 place-items-center rounded-full border border-white/20 text-muted hover:bg-red-950/60 hover:text-red-300 disabled:opacity-40"
          >
            <Trash2 size={15} aria-hidden />
          </button>
        </div>
      </div>
      <dl className="grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
        {[
          ['Recorded', clock(rec.elapsed_ms)],
          ['Size', gb(rec.size_bytes)],
          ['Free space', rec.free_bytes === null ? '—' : gb(rec.free_bytes)],
          ['Marked moments', String(rec.marks.length)]
        ].map(([k, v]) => (
          <div key={k} className="rounded-xl bg-white/[0.04] px-3 py-2">
            <dt className="text-muted">{k}</dt>
            <dd className={`mt-0.5 text-sm font-semibold tabular-nums ${k === 'Free space' && lowDisk ? 'text-amber-300' : ''}`}>{v}</dd>
          </div>
        ))}
      </dl>
      {rec.status === 'reconnecting' && (
        <p className="text-xs text-amber-300">The connection dropped. Reconnecting; nothing recorded so far is lost.</p>
      )}
    </section>
  )
}

function HistoryRow({ rec }: { rec: Recording }) {
  const { saveRecording, discardRecording, openProject } = useApp.getState()
  const projectName = useApp((s) => s.projects.find((p) => p.id === rec.project_id)?.name)
  const failed = rec.status === 'failed'

  return (
    <li className="flex flex-wrap items-center gap-3 border-b border-dashed border-[rgba(160,180,220,0.18)] py-3 last:border-b-0">
      <span
        className={`grid size-8 shrink-0 place-items-center rounded-full ${
          rec.status === 'done' ? 'bg-accent text-on-accent' : failed ? 'bg-danger-subtle text-red-300' : 'bg-white/10 text-muted'
        }`}
        aria-hidden
      >
        {rec.status === 'done' ? <Check size={14} strokeWidth={2.5} /> : failed ? <CircleAlert size={14} /> : <Radio size={14} />}
      </span>
      <div className="min-w-0 flex-[1_1_240px]">
        <div className="truncate text-sm font-semibold">{rec.channel ?? rec.url}</div>
        <div className="truncate text-xs text-muted">
          {STATUS_TEXT[rec.status]} · {new Date(rec.started_at).toLocaleString()} · {clock(rec.elapsed_ms)}
          {rec.marks.length ? ` · ${rec.marks.length} marked` : ''}
          {projectName ? ` · ${projectName}` : ''}
        </div>
        {(rec.error || rec.note) && <div className={`mt-0.5 text-xs ${failed ? 'text-red-300' : 'text-muted'}`}>{rec.error ?? rec.note}</div>}
      </div>
      <div className="flex gap-2">
        {rec.status === 'interrupted' && (
          <button onClick={() => void saveRecording(rec.id)} className="rounded-md bg-accent px-3.5 py-1.5 text-xs font-semibold text-on-accent hover:bg-accent-hover">
            Save recording
          </button>
        )}
        {rec.output_path && (
          <button
            onClick={() => void window.clipping.files.openPath(rec.output_dir)}
            aria-label="Open recordings folder"
            title="Open recordings folder"
            className="not-pill grid size-8 place-items-center rounded-full border border-white/20 text-muted hover:bg-white/10 hover:text-ink"
          >
            <FolderOpen size={14} aria-hidden />
          </button>
        )}
        {rec.status === 'done' && rec.source_id !== null && projectName && (
          <button onClick={() => void openProject(rec.project_id)} className="rounded-md border border-white/20 px-3.5 py-1.5 text-xs hover:bg-white/10">
            Open project
          </button>
        )}
        <button
          onClick={async () => {
            if (rec.status === 'interrupted') {
              const ok = await confirmAction({
                title: 'Discard this recording?',
                message: 'What was recorded before the app closed is deleted.',
                confirmLabel: 'Discard',
                danger: true
              })
              if (!ok) return
            }
            void discardRecording(rec.id)
          }}
          aria-label={rec.status === 'interrupted' ? 'Discard recording' : 'Remove from list'}
          title={rec.status === 'interrupted' ? 'Discard' : 'Remove from list (the saved file is kept)'}
          className="not-pill grid size-8 place-items-center rounded-full text-muted hover:bg-white/10 hover:text-ink"
        >
          <Trash2 size={14} aria-hidden />
        </button>
      </div>
    </li>
  )
}

/** Record live streams from a link: start panel, the live player for what's recording, and this session's list. */
export function LiveView() {
  const recordings = useApp((s) => s.recordings)
  const active = useMemo(() => recordings.filter((r) => RECORDING_ACTIVE.includes(r.status)), [recordings])
  const past = useMemo(() => recordings.filter((r) => !RECORDING_ACTIVE.includes(r.status)), [recordings])

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 px-8 py-7">
      <div>
        <h1 className="text-3xl font-semibold tracking-[-0.02em]">Live</h1>
        <p className="mt-1 text-sm text-muted">
          Watch a stream here while it records. When it ends, the recording goes into your project, ready for Find clips.
        </p>
      </div>

      {active.map((rec) => (
        <ActiveRecording key={rec.id} rec={rec} />
      ))}

      <StartPanel />

      {past.length > 0 && (
        <section className="rounded-2xl border border-line bg-panel px-5 py-2 shadow-card">
          <h2 className="pt-3 text-[15px] font-semibold">Recordings</h2>
          <ul>
            {past.map((rec) => (
              <HistoryRow key={rec.id} rec={rec} />
            ))}
          </ul>
        </section>
      )}
    </div>
  )
}
