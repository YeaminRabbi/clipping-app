import { useEffect, useState, type ReactNode } from 'react'
import type { AnalysisMode, AnalyzeParams, SpeechModel } from '../lib/api'
import { useApp } from '../store'

const PREFS_KEY = 'clipping.autoClipPrefs'

const MODES: { key: AnalysisMode; title: string; text: string }[] = [
  { key: 'talking', title: 'Talking', text: 'Podcasts, interviews, lectures. Picks complete thoughts with strong openings.' },
  { key: 'action', title: 'Action', text: 'Gaming, sports, vlogs. Picks loud, fast-moving moments.' },
  { key: 'even', title: 'Even split', text: 'No scoring: splits the video into evenly spaced parts.' }
]

const LENGTHS: { label: string; min: number; max: number }[] = [
  { label: '15–30 s', min: 15, max: 30 },
  { label: '30–60 s', min: 30, max: 60 },
  { label: '60–90 s', min: 60, max: 90 }
]

const MODELS: { key: SpeechModel; label: string; size: string }[] = [
  { key: 'tiny', label: 'Fast', size: '75 MB' },
  { key: 'base', label: 'Balanced', size: '145 MB' },
  { key: 'small', label: 'Accurate', size: '480 MB' }
]

const LANGUAGES: [string, string][] = [
  ['', 'Detect automatically'],
  ['en', 'English'],
  ['es', 'Spanish'],
  ['pt', 'Portuguese'],
  ['fr', 'French'],
  ['de', 'German'],
  ['it', 'Italian'],
  ['hi', 'Hindi'],
  ['ar', 'Arabic'],
  ['ja', 'Japanese'],
  ['ko', 'Korean'],
  ['zh', 'Chinese']
]

interface Prefs {
  mode: AnalysisMode
  auto: boolean
  count: number
  min: number
  max: number
  model: SpeechModel
  language: string
}

const DEFAULT_PREFS: Prefs = { mode: 'talking', auto: true, count: 5, min: 30, max: 60, model: 'base', language: '' }

function loadPrefs(): Prefs {
  try {
    const raw = localStorage.getItem(PREFS_KEY)
    return raw ? { ...DEFAULT_PREFS, ...JSON.parse(raw) } : DEFAULT_PREFS
  } catch {
    return DEFAULT_PREFS
  }
}

const toClock = (ms: number): string => `${Math.floor(ms / 60000)}:${String(Math.floor((ms % 60000) / 1000)).padStart(2, '0')}`

/** "1:05" or "65" -> 65000 ms; null if unreadable. */
function fromClock(text: string): number | null {
  const parts = text.trim().split(':').map(Number)
  if (parts.some((n) => Number.isNaN(n) || n < 0) || parts.length === 0 || parts.length > 3) return null
  return parts.reduce((total, n) => total * 60 + n, 0) * 1000
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <h3 className="mb-2 text-sm font-medium">{title}</h3>
      {children}
    </section>
  )
}

const inputClass = 'rounded-md border border-line bg-panel-2 px-2.5 py-1.5 text-sm outline-none focus:border-accent'

export function AutoClipDialog() {
  const dialog = useApp((s) => s.autoClipDialog)
  const source = useApp((s) => s.sources.find((x) => x.id === s.autoClipDialog?.sourceId))
  const suggestedCount = useApp((s) => s.clips.filter((c) => c.source_id === dialog?.sourceId && c.status === 'suggested').length)
  const keptCount = useApp((s) => s.clips.filter((c) => c.source_id === dialog?.sourceId && c.status !== 'suggested').length)
  const { closeAutoClipDialog, analyze } = useApp.getState()

  const [prefs, setPrefs] = useState<Prefs>(loadPrefs)
  const [keywords, setKeywords] = useState('')
  const [useRange, setUseRange] = useState(dialog?.range != null)
  const [from, setFrom] = useState(toClock(dialog?.range?.start ?? 0))
  const [to, setTo] = useState(toClock(dialog?.range?.end ?? source?.duration_ms ?? 0))
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && closeAutoClipDialog()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [closeAutoClipDialog])

  if (!dialog || !source) return null
  const duration = source.duration_ms ?? 0
  const rangeStart = useRange ? fromClock(from) : 0
  const rangeEnd = useRange ? fromClock(to) : duration
  const lengthPreset = LENGTHS.find((l) => l.min === prefs.min && l.max === prefs.max)

  let problem: string | null = null
  if (prefs.min < 3 || prefs.max > 180) problem = 'Clip length must be between 3 and 180 seconds.'
  else if (prefs.max < prefs.min) problem = 'The longest length must be at least the shortest.'
  else if (rangeStart === null || rangeEnd === null) problem = 'Enter times like 1:30.'
  else if (rangeEnd <= rangeStart) problem = 'The part to analyze must end after it starts.'
  else if (Math.min(rangeEnd, duration) - rangeStart < prefs.min * 1000) problem = 'That part is shorter than the shortest clip length.'
  else if (!prefs.auto && (prefs.count < 1 || prefs.count > 50)) problem = 'Choose between 1 and 50 clips.'

  const submit = async () => {
    if (problem) return
    const params: AnalyzeParams = {
      mode: prefs.mode,
      clip_count: prefs.auto ? null : prefs.count,
      min_seconds: prefs.min,
      max_seconds: prefs.max,
      keywords: prefs.mode === 'even' ? [] : keywords.split(',').map((k) => k.trim()).filter(Boolean),
      range_start_ms: useRange ? rangeStart : null,
      range_end_ms: useRange ? Math.min(rangeEnd ?? duration, duration) : null,
      model: prefs.model,
      language: prefs.language || null
    }
    setBusy(true)
    const ok = await analyze(source.id, params)
    setBusy(false)
    if (ok) {
      try {
        localStorage.setItem(PREFS_KEY, JSON.stringify(prefs))
      } catch {
        // Remembering settings is a convenience only.
      }
      closeAutoClipDialog()
    }
  }

  const set = (patch: Partial<Prefs>) => setPrefs({ ...prefs, ...patch })

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/70 p-6" onMouseDown={closeAutoClipDialog}>
      <div
        className="flex max-h-full w-full max-w-2xl flex-col overflow-hidden rounded-xl border border-line bg-panel shadow-2xl"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="border-b border-line px-5 py-4">
          <h2 className="text-base font-semibold">Find clips automatically</h2>
          <p className="mt-0.5 truncate text-xs text-muted">{source.title}</p>
        </div>

        <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-auto p-5">
          <Section title="What kind of video is it?">
            <div className="grid grid-cols-3 gap-2">
              {MODES.map((m) => (
                <button
                  key={m.key}
                  onClick={() => set({ mode: m.key })}
                  className={`rounded-lg border p-3 text-left ${prefs.mode === m.key ? 'border-accent bg-accent/15' : 'border-line hover:bg-panel-2'}`}
                >
                  <div className="text-sm font-medium">{m.title}</div>
                  <div className="mt-1 text-[11px] leading-snug text-muted">{m.text}</div>
                </button>
              ))}
            </div>
          </Section>

          <div className="grid grid-cols-2 gap-5">
            <Section title="How many clips?">
              <div className="flex items-center gap-3">
                <label className="flex cursor-pointer items-center gap-2 text-sm">
                  <input type="radio" checked={prefs.auto} onChange={() => set({ auto: true })} className="accent-[#7c5cff]" />
                  Auto
                </label>
                <label className="flex cursor-pointer items-center gap-2 text-sm">
                  <input type="radio" checked={!prefs.auto} onChange={() => set({ auto: false })} className="accent-[#7c5cff]" />
                  Exactly
                </label>
                <input
                  type="number"
                  min={1}
                  max={50}
                  value={prefs.count}
                  disabled={prefs.auto}
                  onChange={(e) => set({ count: Number(e.target.value), auto: false })}
                  className={`${inputClass} w-20 disabled:opacity-40`}
                />
              </div>
              <p className="mt-1.5 text-[11px] text-muted">
                {prefs.auto ? 'Picks a number that suits the video’s length.' : 'Fewer may be made if not enough fit.'}
              </p>
            </Section>

            <Section title="Clip length">
              <div className="flex flex-wrap gap-1.5">
                {LENGTHS.map((l) => (
                  <button
                    key={l.label}
                    onClick={() => set({ min: l.min, max: l.max })}
                    className={`rounded-md border px-2.5 py-1 text-xs ${lengthPreset === l ? 'border-accent bg-accent/15' : 'border-line text-muted hover:bg-panel-2'}`}
                  >
                    {l.label}
                  </button>
                ))}
              </div>
              <div className="mt-2 flex items-center gap-2 text-xs text-muted">
                <input type="number" min={3} max={180} value={prefs.min} onChange={(e) => set({ min: Number(e.target.value) })} className={`${inputClass} w-16`} />
                to
                <input type="number" min={3} max={180} value={prefs.max} onChange={(e) => set({ max: Number(e.target.value) })} className={`${inputClass} w-16`} />
                seconds
              </div>
            </Section>
          </div>

          {prefs.mode !== 'even' && (
            <Section title="Keywords (optional)">
              <input
                value={keywords}
                onChange={(e) => setKeywords(e.target.value)}
                placeholder="pricing, growth, mistake"
                className={`${inputClass} w-full`}
              />
              <p className="mt-1.5 text-[11px] text-muted">Moments that mention these words are ranked higher. Separate with commas.</p>
            </Section>
          )}

          <Section title="Part of the video">
            <div className="flex flex-wrap items-center gap-3 text-sm">
              <label className="flex cursor-pointer items-center gap-2">
                <input type="radio" checked={!useRange} onChange={() => setUseRange(false)} className="accent-[#7c5cff]" />
                All of it
              </label>
              <label className="flex cursor-pointer items-center gap-2">
                <input type="radio" checked={useRange} onChange={() => setUseRange(true)} className="accent-[#7c5cff]" />
                From
              </label>
              <input value={from} onChange={(e) => setFrom(e.target.value)} disabled={!useRange} className={`${inputClass} w-20 disabled:opacity-40`} />
              <span className="text-muted">to</span>
              <input value={to} onChange={(e) => setTo(e.target.value)} disabled={!useRange} className={`${inputClass} w-20 disabled:opacity-40`} />
            </div>
          </Section>

          {prefs.mode !== 'even' && (
            <details className="rounded-md border border-line px-3 py-2">
              <summary className="cursor-pointer text-sm text-muted">Speech recognition</summary>
              <div className="mt-3 grid grid-cols-2 gap-4">
                <label className="flex flex-col gap-1.5">
                  <span className="text-xs text-muted">Accuracy</span>
                  <select value={prefs.model} onChange={(e) => set({ model: e.target.value as SpeechModel })} className={inputClass}>
                    {MODELS.map((m) => (
                      <option key={m.key} value={m.key}>
                        {m.label} ({m.size} download, once)
                      </option>
                    ))}
                  </select>
                </label>
                <label className="flex flex-col gap-1.5">
                  <span className="text-xs text-muted">Language</span>
                  <select value={prefs.language} onChange={(e) => set({ language: e.target.value })} className={inputClass}>
                    {LANGUAGES.map(([code, name]) => (
                      <option key={code} value={code}>
                        {name}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              <p className="mt-2 text-[11px] text-muted">
                Speech is recognised on this computer; nothing is uploaded. The model downloads the first time it’s used.
              </p>
            </details>
          )}
        </div>

        <div className="flex items-center justify-between gap-4 border-t border-line px-5 py-3">
          <span className={`text-xs ${problem ? 'text-amber-300' : 'text-muted'}`}>
            {problem ??
              (suggestedCount > 0
                ? `Replaces the ${suggestedCount} suggested clip${suggestedCount === 1 ? '' : 's'}${keptCount ? `; your ${keptCount} edited clip${keptCount === 1 ? ' is' : 's are'} kept` : ''}.`
                : keptCount
                  ? `Your ${keptCount} existing clip${keptCount === 1 ? ' is' : 's are'} kept; new clips won’t overlap them.`
                  : 'Clips appear in the editor as suggestions you can trim, frame or replace.')}
          </span>
          <div className="flex shrink-0 gap-2">
            <button onClick={closeAutoClipDialog} className="rounded-md px-4 py-2 text-sm text-muted hover:bg-panel-2">
              Cancel
            </button>
            <button
              onClick={() => void submit()}
              disabled={busy || problem !== null}
              className="rounded-md bg-accent px-4 py-2 text-sm font-medium hover:bg-accent-hover disabled:opacity-50"
            >
              {busy ? 'Starting…' : 'Find clips'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
