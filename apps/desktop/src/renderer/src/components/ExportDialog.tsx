import { useEffect, useMemo, useState, type ReactNode } from 'react'
import type { ExportPreset } from '../lib/api'
import { ASPECTS } from '../lib/aspects'
import { shortDuration } from '../lib/time'
import { useApp } from '../store'

const PRESET_STORAGE_KEY = 'clipping.exportPreset'
const DEFAULT_TEMPLATE = '{project}_{index}_{title}_{ratio}'

type SavedPreset = Omit<ExportPreset, 'output_dir'> & { output_dir?: string }

const DEFAULTS: SavedPreset = {
  codec: 'h264',
  quality: 'high',
  resolution: 1080,
  fps: 'source',
  hardware: true,
  default_framing: 'smart',
  captions: 'off',
  zip: false,
  name_template: DEFAULT_TEMPLATE
}

function loadSaved(): SavedPreset {
  try {
    const raw = localStorage.getItem(PRESET_STORAGE_KEY)
    return raw ? { ...DEFAULTS, ...JSON.parse(raw) } : DEFAULTS
  } catch {
    return DEFAULTS
  }
}

function save(preset: ExportPreset): void {
  try {
    localStorage.setItem(PRESET_STORAGE_KEY, JSON.stringify(preset))
  } catch {
    // Remembering settings is a convenience only.
  }
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="text-xs text-muted">{label}</span>
      {children}
    </label>
  )
}

const selectClass = 'rounded-md border border-line bg-panel-2 px-2.5 py-2 text-sm outline-none focus:border-accent'

export function ExportDialog() {
  const initial = useApp((s) => s.exportDialog)
  const clips = useApp((s) => s.clips)
  const sources = useApp((s) => s.sources)
  const project = useApp((s) => s.projects.find((p) => p.id === s.openProjectId))
  const { closeExportDialog, startExport } = useApp.getState()

  const [selected, setSelected] = useState<Set<number>>(new Set(initial ?? []))
  const [aspects, setAspects] = useState<Set<string>>(() => {
    // Default to the ratios already framed in the editor, else phone.
    const used = new Set(clips.filter((c) => initial?.includes(c.id)).flatMap((c) => Object.keys(c.formats)))
    return used.size ? used : new Set(['9:16'])
  })
  const [preset, setPreset] = useState<SavedPreset>(loadSaved)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!preset.output_dir && project) {
      void window.clipping.files.defaultExportDir(project.name).then((dir) => setPreset((p) => ({ ...p, output_dir: dir })))
    }
  }, [preset.output_dir, project])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && closeExportDialog()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [closeExportDialog])

  const groups = useMemo(
    () =>
      sources
        .map((s) => ({ source: s, clips: clips.filter((c) => c.source_id === s.id) }))
        .filter((g) => g.clips.length > 0),
    [sources, clips]
  )

  const total = selected.size * aspects.size
  const exampleName = useMemo(() => {
    const clip = clips.find((c) => selected.has(c.id))
    const values: Record<string, string> = {
      project: project?.name ?? 'Project',
      source: sources.find((s) => s.id === clip?.source_id)?.title ?? 'Video',
      title: clip?.title ?? 'Clip 1',
      index: '01',
      ratio: ([...aspects][0] ?? '9:16').replace(':', 'x')
    }
    return (
      preset.name_template.replace(/\{(\w+)\}/g, (m, k: string) => values[k] ?? m).replace(/[<>:"/\\|?*]/g, '') + '.mp4'
    )
  }, [preset.name_template, clips, selected, aspects, project, sources])

  const toggle = <T,>(set: Set<T>, value: T): Set<T> => {
    const next = new Set(set)
    if (next.has(value)) next.delete(value)
    else next.add(value)
    return next
  }

  const submit = async () => {
    if (!preset.output_dir) return
    const full: ExportPreset = { ...preset, output_dir: preset.output_dir }
    setBusy(true)
    // Keep the editor's clip order, so {index} matches the clip list.
    const ordered = clips.filter((c) => selected.has(c.id)).map((c) => c.id)
    const ok = await startExport(ordered, [...aspects], full)
    setBusy(false)
    if (ok) {
      save(full)
      closeExportDialog()
    }
  }

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/70 p-6" onMouseDown={closeExportDialog}>
      <div
        className="flex max-h-full w-full max-w-3xl flex-col overflow-hidden rounded-xl border border-line bg-panel shadow-2xl"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="border-b border-line px-5 py-4">
          <h2 className="text-base font-semibold">Export clips</h2>
          <p className="mt-0.5 text-xs text-muted">Clips are rendered from the original video at full quality.</p>
        </div>

        <div className="grid min-h-0 flex-1 grid-cols-1 gap-6 overflow-auto p-5 md:grid-cols-[1fr_1fr]">
          <section>
            <div className="mb-2 flex items-center justify-between">
              <h3 className="text-sm font-medium">Clips</h3>
              <button
                onClick={() => setSelected(selected.size === clips.length ? new Set() : new Set(clips.map((c) => c.id)))}
                className="text-xs text-muted hover:text-white"
              >
                {selected.size === clips.length ? 'Select none' : 'Select all'}
              </button>
            </div>
            <div className="flex max-h-80 flex-col gap-3 overflow-auto rounded-md border border-line p-2">
              {groups.map(({ source, clips: list }) => (
                <div key={source.id}>
                  <div className="truncate px-1 pb-1 text-[11px] text-muted">{source.title}</div>
                  {list.map((clip) => (
                    <label key={clip.id} className="flex cursor-pointer items-center gap-2 rounded px-1.5 py-1 hover:bg-panel-2">
                      <input
                        type="checkbox"
                        checked={selected.has(clip.id)}
                        onChange={() => setSelected(toggle(selected, clip.id))}
                        className="accent-[#7c5cff]"
                      />
                      <span className="min-w-0 flex-1 truncate text-sm">{clip.title}</span>
                      <span className="text-[11px] text-muted">{shortDuration(clip.end_ms - clip.start_ms)}</span>
                    </label>
                  ))}
                </div>
              ))}
            </div>

            <h3 className="mt-5 mb-2 text-sm font-medium">Sizes</h3>
            <div className="flex flex-col gap-1">
              {ASPECTS.map((a) => (
                <label key={a.key} className="flex cursor-pointer items-center gap-2 rounded px-1.5 py-1 hover:bg-panel-2">
                  <input
                    type="checkbox"
                    checked={aspects.has(a.key)}
                    onChange={() => setAspects(toggle(aspects, a.key))}
                    className="accent-[#7c5cff]"
                  />
                  <span className="w-10 text-sm">{a.key}</span>
                  <span className="text-xs text-muted">{a.label}</span>
                </label>
              ))}
            </div>
            <label className="mt-3 flex flex-col gap-1.5">
              <span className="text-xs text-muted">Sizes you didn’t frame in the editor</span>
              <select
                value={preset.default_framing}
                onChange={(e) => setPreset({ ...preset, default_framing: e.target.value as ExportPreset['default_framing'] })}
                className={selectClass}
              >
                <option value="smart">Smart: follow faces</option>
                <option value="center">Centered crop</option>
                <option value="fit">Fit: whole frame, blurred background</option>
              </select>
            </label>
            <p className="mt-1.5 text-[11px] text-muted">Framing you set in the editor is always used as is.</p>
          </section>

          <section className="flex flex-col gap-4">
            <div className="grid grid-cols-2 gap-3">
              <Field label="Quality">
                <select
                  value={preset.quality}
                  onChange={(e) => setPreset({ ...preset, quality: e.target.value as ExportPreset['quality'] })}
                  className={selectClass}
                >
                  <option value="high">High</option>
                  <option value="balanced">Balanced</option>
                  <option value="small">Smaller files</option>
                </select>
              </Field>
              <Field label="Resolution">
                <select
                  value={preset.resolution}
                  onChange={(e) => setPreset({ ...preset, resolution: Number(e.target.value) as ExportPreset['resolution'] })}
                  className={selectClass}
                >
                  <option value={1080}>1080p</option>
                  <option value={720}>720p</option>
                </select>
              </Field>
              <Field label="Format">
                <select
                  value={preset.codec}
                  onChange={(e) => setPreset({ ...preset, codec: e.target.value as ExportPreset['codec'] })}
                  className={selectClass}
                >
                  <option value="h264">MP4 · H.264 (plays everywhere)</option>
                  <option value="hevc">MP4 · H.265 (smaller)</option>
                </select>
              </Field>
              <Field label="Frame rate">
                <select
                  value={preset.fps}
                  onChange={(e) => setPreset({ ...preset, fps: e.target.value as ExportPreset['fps'] })}
                  className={selectClass}
                >
                  <option value="source">Same as video</option>
                  <option value="30">30 fps</option>
                  <option value="60">60 fps</option>
                </select>
              </Field>
            </div>

            <Field label="Captions">
              <select
                value={preset.captions}
                onChange={(e) => setPreset({ ...preset, captions: e.target.value as ExportPreset['captions'] })}
                className={selectClass}
              >
                <option value="off">No captions</option>
                <option value="burn">Burn into the video</option>
                <option value="burn_srt">Burn in + .srt subtitle file</option>
                <option value="srt">.srt subtitle file only</option>
              </select>
              {preset.captions !== 'off' && (
                <span className="text-[11px] text-muted">
                  Uses each clip’s captions and the project’s caption style. Videos that weren’t transcribed are transcribed
                  first, which takes longer.
                </span>
              )}
            </Field>

            <label className="flex cursor-pointer items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={preset.zip}
                onChange={(e) => setPreset({ ...preset, zip: e.target.checked })}
                className="accent-[#7c5cff]"
              />
              Also bundle everything into one ZIP file
            </label>

            <label className="flex cursor-pointer items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={preset.hardware}
                onChange={(e) => setPreset({ ...preset, hardware: e.target.checked })}
                className="accent-[#7c5cff]"
              />
              Use the graphics card when available (faster)
            </label>

            <Field label="Save to">
              <div className="flex gap-2">
                <input
                  value={preset.output_dir ?? ''}
                  onChange={(e) => setPreset({ ...preset, output_dir: e.target.value })}
                  className={`${selectClass} min-w-0 flex-1`}
                />
                <button
                  onClick={async () => {
                    const dir = await window.clipping.files.pickFolder(preset.output_dir)
                    if (dir) setPreset({ ...preset, output_dir: dir })
                  }}
                  className="rounded-md border border-line px-3 text-sm hover:bg-panel-2"
                >
                  Change…
                </button>
              </div>
            </Field>

            <Field label="File names">
              <input
                value={preset.name_template}
                onChange={(e) => setPreset({ ...preset, name_template: e.target.value })}
                className={selectClass}
              />
              <span className="text-[11px] text-muted">
                Use {'{project}'} {'{source}'} {'{title}'} {'{index}'} {'{ratio}'} · e.g. <span className="text-white">{exampleName}</span>
              </span>
            </Field>
          </section>
        </div>

        <div className="flex items-center justify-between border-t border-line px-5 py-3">
          <span className="text-xs text-muted">
            {total === 0 ? 'Pick at least one clip and one size' : `${total} video${total === 1 ? '' : 's'} will be created`}
          </span>
          <div className="flex gap-2">
            <button onClick={closeExportDialog} className="rounded-md px-4 py-2 text-sm text-muted hover:bg-panel-2">
              Cancel
            </button>
            <button
              onClick={() => void submit()}
              disabled={busy || total === 0 || !preset.output_dir || !preset.name_template.trim()}
              className="rounded-md bg-accent px-4 py-2 text-sm font-medium hover:bg-accent-hover disabled:opacity-50"
            >
              {busy ? 'Starting…' : `Export ${total || ''}`}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
