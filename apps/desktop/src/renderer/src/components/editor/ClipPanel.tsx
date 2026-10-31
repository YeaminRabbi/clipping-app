import { useEffect, useState, type ReactNode } from 'react'
import type { Clip, FitStyle, FramingMode } from '../../lib/api'
import { ASPECTS } from '../../lib/aspects'
import { shortDuration, timecode } from '../../lib/time'
import { AnalysisStatus } from '../AnalysisStatus'
import type { Range } from './Timeline'

function ScoreBadge({ score }: { score: number }) {
  const color =
    score >= 60 ? 'bg-emerald-500/20 text-emerald-300' : score >= 35 ? 'bg-amber-500/20 text-amber-300' : 'bg-white/10 text-muted'
  return (
    <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${color}`} title="How strong this moment looks (0–100)">
      {Math.round(score)}
    </span>
  )
}

const MODES: [FramingMode, string, string][] = [
  ['manual', 'Crop', 'A fixed crop you position yourself'],
  ['smart', 'Smart', 'Follows faces automatically'],
  ['fit', 'Fit', 'Keeps the whole frame over a background']
]

function SmartInfo({ tracking, faceRatio, stale, onRetrack }: Props) {
  if (tracking) {
    return (
      <p className="mt-2 flex items-center gap-2 text-xs text-muted">
        <span className="size-3 animate-spin rounded-full border-2 border-accent border-t-transparent" />
        Finding faces…
      </p>
    )
  }
  return (
    <div className="mt-2 text-[11px] text-muted">
      {stale ? (
        <span className="text-amber-300">The clip changed since faces were tracked. </span>
      ) : faceRatio === null ? null : faceRatio === 0 ? (
        <span className="text-amber-300">No faces found, so the crop stays centered. </span>
      ) : (
        <span>Faces found in {Math.round(faceRatio * 100)}% of the clip. </span>
      )}
      <button onClick={onRetrack} className="text-white/80 underline-offset-2 hover:text-white hover:underline">
        Track again
      </button>
    </div>
  )
}

function FitControls({ style, onChange, onCommit }: { style: FitStyle; onChange(s: FitStyle): void; onCommit(s: FitStyle): void }) {
  const choice = <K extends keyof FitStyle>(key: K, options: [FitStyle[K], string][]) => (
    <div className="flex rounded-md border border-line p-0.5">
      {options.map(([value, label]) => (
        <button
          key={String(value)}
          onClick={() => onCommit({ ...style, [key]: value })}
          className={`flex-1 rounded px-2 py-1 ${style[key] === value ? 'bg-panel-2 text-white' : 'text-muted hover:text-white'}`}
        >
          {label}
        </button>
      ))}
    </div>
  )
  // Sliders preview live and save when released.
  const slider = (key: 'dim' | 'zoom', min: number, max: number, label: string, shown: string) => (
    <label className="flex flex-col gap-1">
      <span className="flex justify-between text-muted">
        {label} <span className="text-white/80">{shown}</span>
      </span>
      <input
        type="range"
        min={min}
        max={max}
        step={0.05}
        value={style[key]}
        onChange={(e) => onChange({ ...style, [key]: Number(e.target.value) })}
        onPointerUp={() => onCommit(style)}
        onKeyUp={() => onCommit(style)}
        className="accent-[#7c5cff]"
      />
    </label>
  )
  return (
    <div className="mt-3 flex flex-col gap-3 text-xs">
      <div className="flex flex-col gap-1">
        <span className="text-muted">Background</span>
        {choice('background', [['blur', 'Blurred'], ['black', 'Black'], ['white', 'White']])}
      </div>
      {style.background === 'blur' && slider('dim', 0, 0.6, 'Darken background', `${Math.round(style.dim * 100)}%`)}
      {slider('zoom', 1, 1.5, 'Zoom in', `${Math.round(style.zoom * 100)}%`)}
      <div className="flex flex-col gap-1">
        <span className="text-muted">Position</span>
        {choice('position', [['center', 'Middle'], ['top', 'Near the top']])}
      </div>
    </div>
  )
}

interface Props {
  tracking: boolean
  faceRatio: number | null
  stale: boolean
  fit: FitStyle
  onRetrack(): void
  onFitChange(style: FitStyle): void
  onFitCommit(style: FitStyle): void
  sourceId: number
  canReplace: boolean
  clips: Clip[]
  selected: Clip | null
  range: Range | null
  fps: number
  aspect: string
  mode: FramingMode
  onSelect(id: number | null): void
  onAdd(): void
  onAspect(aspect: string): void
  onMode(mode: FramingMode): void
  onResetCrop(): void
  onNudge(edge: 'start' | 'end', frames: number): void
  onTitle(title: string): void
  onDelete(): void
  onAutoClip(): void
  onReplace(): void
  /** Contents of the Captions tab (shown for the selected clip). */
  captionsTab: ReactNode
}

export function ClipPanel(props: Props) {
  const { clips, selected, range, fps, aspect, mode } = props
  const [title, setTitle] = useState(selected?.title ?? '')
  const [tab, setTab] = useState<'frame' | 'captions'>('frame')
  useEffect(() => setTitle(selected?.title ?? ''), [selected?.id, selected?.title])

  const saveTitle = () => {
    if (selected && title.trim() && title.trim() !== selected.title) props.onTitle(title.trim())
    else setTitle(selected?.title ?? '')
  }

  const nudge = (edge: 'start' | 'end') => (
    <span className="flex">
      <button onClick={() => props.onNudge(edge, -1)} className="rounded-l border border-line px-1.5 hover:bg-panel" title="1 frame earlier">
        ‹
      </button>
      <button onClick={() => props.onNudge(edge, 1)} className="rounded-r border border-l-0 border-line px-1.5 hover:bg-panel" title="1 frame later">
        ›
      </button>
    </span>
  )

  return (
    <aside className="flex w-80 shrink-0 flex-col overflow-hidden border-l border-line bg-panel">
      <div className="flex items-center justify-between border-b border-line px-4 py-3">
        <h3 className="text-sm font-semibold">
          Clips <span className="font-normal text-muted">({clips.length})</span>
        </h3>
        <div className="flex gap-1.5">
          <button
            onClick={props.onAutoClip}
            className="rounded-md border border-accent/60 px-2.5 py-1.5 text-xs font-medium hover:bg-accent/20"
            title="Find the best moments automatically"
          >
            Find clips
          </button>
          <button
            onClick={props.onAdd}
            className="rounded-md bg-accent px-2.5 py-1.5 text-xs font-medium hover:bg-accent-hover"
            title="Add clip (N)"
          >
            {selected === null && range ? 'Add marked' : '+ New'}
          </button>
        </div>
      </div>
      <div className="border-b border-line p-2 empty:hidden">
        <AnalysisStatus sourceId={props.sourceId} />
      </div>

      <ul className="max-h-[40%] shrink-0 overflow-auto border-b border-line p-2">
        {clips.length === 0 && (
          <li className="px-2 py-6 text-center text-xs text-muted">
            No clips yet. Click “Find clips” to pick the best moments automatically, or mark a range with <kbd>I</kbd> /{' '}
            <kbd>O</kbd> and press <kbd>N</kbd>.
          </li>
        )}
        {clips.map((clip, i) => (
          <li key={clip.id}>
            <button
              onClick={() => props.onSelect(clip.id === selected?.id ? null : clip.id)}
              className={`flex w-full items-center gap-3 rounded-md px-2.5 py-2 text-left ${
                clip.id === selected?.id ? 'bg-amber-400/15 ring-1 ring-amber-400/60' : 'hover:bg-panel-2'
              }`}
            >
              <span className="w-5 text-right text-xs text-muted">{i + 1}</span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm">{clip.title}</span>
                <span className="text-[11px] text-muted">
                  {timecode(clip.start_ms, fps)} · {shortDuration(clip.end_ms - clip.start_ms)}
                  {clip.status === 'suggested' && <span className="ml-1 text-accent">· suggested</span>}
                </span>
              </span>
              {clip.score !== null && <ScoreBadge score={clip.score} />}
              {Object.keys(clip.formats).length > 0 && (
                <span className="text-[10px] text-muted">{Object.keys(clip.formats).join(' ')}</span>
              )}
            </button>
          </li>
        ))}
      </ul>

      <div className="flex border-b border-line px-2 text-xs">
        {(['frame', 'captions'] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`-mb-px border-b-2 px-3 py-2 ${tab === t ? 'border-accent text-white' : 'border-transparent text-muted hover:text-white'}`}
          >
            {t === 'frame' ? 'Frame & clip' : 'Captions'}
          </button>
        ))}
      </div>
      {tab === 'captions' && (
        <div className="flex-1 overflow-auto p-4">
          {selected ? props.captionsTab : <p className="text-xs text-muted">Select a clip to see and edit its captions.</p>}
        </div>
      )}
      <div className={`flex-1 overflow-auto p-4 ${tab === 'frame' ? '' : 'hidden'}`}>
        <section>
          <h4 className="text-xs font-semibold tracking-wide text-muted uppercase">Frame</h4>
          <div className="mt-2 grid grid-cols-5 gap-1.5">
            {ASPECTS.map((a) => (
              <button
                key={a.key}
                onClick={() => props.onAspect(a.key)}
                title={a.label}
                className={`flex flex-col items-center gap-1 rounded-md border px-1 py-2 text-[10px] ${
                  aspect === a.key ? 'border-accent bg-accent/15 text-white' : 'border-line text-muted hover:bg-panel-2'
                }`}
              >
                <span
                  className="block border border-current"
                  style={a.ratio < 1 ? { width: 22 * a.ratio, height: 22 } : { width: 22, height: 22 / a.ratio }}
                />
                {a.key}
              </button>
            ))}
          </div>
          <p className="mt-1.5 text-[11px] text-muted">{ASPECTS.find((a) => a.key === aspect)?.label}</p>

          <div className="mt-3 flex rounded-md border border-line p-0.5 text-xs">
            {MODES.map(([m, label, hint]) => (
              <button
                key={m}
                disabled={!selected || props.tracking}
                onClick={() => props.onMode(m)}
                title={hint}
                className={`flex-1 rounded px-2 py-1.5 disabled:opacity-50 ${mode === m ? 'bg-panel-2 text-white' : 'text-muted hover:text-white'}`}
              >
                {label}
              </button>
            ))}
          </div>
          {selected && mode === 'manual' && (
            <button onClick={props.onResetCrop} className="mt-2 text-xs text-muted hover:text-white">
              Center the crop
            </button>
          )}
          {selected && mode === 'smart' && <SmartInfo {...props} />}
          {selected && mode === 'fit' && <FitControls style={props.fit} onChange={props.onFitChange} onCommit={props.onFitCommit} />}
          {!selected && <p className="mt-2 text-[11px] text-muted">Select or add a clip to adjust its framing.</p>}
        </section>

        {selected && range && (
          <section className="mt-6">
            <h4 className="text-xs font-semibold tracking-wide text-muted uppercase">Clip</h4>
            <input
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              onBlur={saveTitle}
              onKeyDown={(e) => {
                if (e.key === 'Enter') e.currentTarget.blur()
                if (e.key === 'Escape') {
                  setTitle(selected.title)
                  e.currentTarget.blur()
                }
              }}
              className="mt-2 w-full rounded-md border border-line bg-panel-2 px-3 py-2 text-sm outline-none focus:border-accent"
              placeholder="Clip title"
            />
            <dl className="mt-3 grid grid-cols-[auto_1fr_auto] items-center gap-x-3 gap-y-2 text-xs">
              <dt className="text-muted">Start</dt>
              <dd className="font-mono">{timecode(range.start, fps)}</dd>
              {nudge('start')}
              <dt className="text-muted">End</dt>
              <dd className="font-mono">{timecode(range.end, fps)}</dd>
              {nudge('end')}
              <dt className="text-muted">Length</dt>
              <dd className="font-mono">{((range.end - range.start) / 1000).toFixed(2)}s</dd>
              <span />
            </dl>
            {selected.reasons.length > 0 && (
              <div className="mt-4">
                <div className="mb-1.5 flex items-center gap-2 text-xs text-muted">
                  Why it was picked {selected.score !== null && <ScoreBadge score={selected.score} />}
                </div>
                <div className="flex flex-wrap gap-1">
                  {selected.reasons.map((r) => (
                    <span
                      key={r}
                      className={`rounded px-1.5 py-0.5 text-[11px] ${r === 'starts mid-thought' ? 'bg-amber-950/60 text-amber-300' : 'bg-panel-2 text-white/90'}`}
                    >
                      {r}
                    </span>
                  ))}
                </div>
              </div>
            )}
            <div className="mt-5 flex gap-1">
              {props.canReplace && (
                <button
                  onClick={props.onReplace}
                  className="rounded-md border border-line px-2.5 py-1 text-xs hover:bg-panel-2"
                  title="Swap for the next-best moment"
                >
                  Replace with another
                </button>
              )}
              <button
                onClick={props.onDelete}
                className="rounded-md px-2.5 py-1 text-xs text-muted hover:bg-red-950/60 hover:text-red-300"
              >
                Delete clip
              </button>
            </div>
          </section>
        )}
      </div>
    </aside>
  )
}
