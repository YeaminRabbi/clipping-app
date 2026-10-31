import { useEffect, useState } from 'react'
import type { CaptionCue, CaptionOverrides, CaptionStyle, CaptionTemplate, ClipCaptions, SpeechModel } from '../../lib/api'
import { useApp } from '../../store'
import { AnalysisStatus } from '../AnalysisStatus'
import { captionTextStyle } from './CaptionOverlay'

const TEMPLATE_INFO: Record<CaptionTemplate, { name: string; sample: string }> = {
  bold_pop: { name: 'Bold pop', sample: 'Big bold words' },
  karaoke: { name: 'Karaoke', sample: 'Words fill as spoken' },
  classic: { name: 'Classic', sample: 'Subtitles in a box' },
  minimal: { name: 'Minimal', sample: 'Clean and simple' }
}

const MODELS: [SpeechModel, string][] = [
  ['tiny', 'Fast'],
  ['base', 'Balanced'],
  ['small', 'Accurate']
]

const relTime = (ms: number): string => `${Math.floor(ms / 60000)}:${((ms % 60000) / 1000).toFixed(1).padStart(4, '0')}`

interface Props {
  sourceId: number
  clipStart: number
  captions: ClipCaptions | null
  loading: boolean
  showOverlay: boolean
  onShowOverlay(show: boolean): void
  onEdit(cue: CaptionCue, text: string): void
  onReset(): void
  onSeek(ms: number): void
}

function CueRow({ cue, clipStart, onEdit, onSeek }: { cue: CaptionCue; clipStart: number; onEdit(text: string): void; onSeek(): void }) {
  const [text, setText] = useState(cue.text)
  useEffect(() => setText(cue.text), [cue.text])
  const commit = () => {
    if (text.trim() !== cue.text) onEdit(text.trim())
  }
  return (
    <li className="flex items-center gap-1.5">
      <button onClick={onSeek} className="w-12 shrink-0 text-left font-mono text-[11px] text-muted hover:text-white" title="Go to this caption">
        {relTime(Math.max(0, cue.start - clipStart))}
      </button>
      <input
        value={text}
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Enter') e.currentTarget.blur()
          if (e.key === 'Escape') {
            setText(cue.text)
            e.currentTarget.blur()
          }
        }}
        className="min-w-0 flex-1 rounded border border-transparent bg-panel-2 px-2 py-1 text-xs outline-none hover:border-line focus:border-accent"
      />
      <button onClick={() => onEdit('')} className="px-1 text-xs text-muted hover:text-red-300" title="Remove this caption">
        ×
      </button>
    </li>
  )
}

export function CaptionsPanel(props: Props) {
  const { captions, loading, sourceId } = props
  const templates = useApp((s) => s.captionTemplates)
  const projectStyle = useApp((s) => s.captionStyle)
  const transcribing = useApp((s) => s.analyses[sourceId]?.task === 'transcribe' && ['queued', 'running'].includes(s.analyses[sourceId]?.status))
  const { setCaptionStyle, transcribe } = useApp.getState()
  const [model, setModel] = useState<SpeechModel>('base')
  const [draft, setDraft] = useState<CaptionOverrides | null>(null)

  if (!templates || !projectStyle) return <p className="text-xs text-muted">Loading…</p>
  const overrides = draft ?? projectStyle.overrides
  const style: CaptionStyle = { ...projectStyle.style, ...overrides }
  const save = (next: CaptionOverrides) => {
    setDraft(null)
    void setCaptionStyle(projectStyle.template, next)
  }

  return (
    <div className="flex flex-col gap-5">
      <section>
        <div className="flex items-center justify-between">
          <h4 className="text-xs font-semibold tracking-wide text-muted uppercase">Caption style</h4>
          <label className="flex cursor-pointer items-center gap-1.5 text-[11px] text-muted">
            <input type="checkbox" checked={props.showOverlay} onChange={(e) => props.onShowOverlay(e.target.checked)} className="accent-[#7c5cff]" />
            Show in preview
          </label>
        </div>
        <div className="mt-2 grid grid-cols-2 gap-1.5">
          {(Object.keys(TEMPLATE_INFO) as CaptionTemplate[]).map((key) => {
            const t = templates.templates[key]
            const selected = projectStyle.template === key
            return (
              <button
                key={key}
                onClick={() => void setCaptionStyle(key, {})}
                className={`flex h-16 flex-col items-center justify-center gap-1 overflow-hidden rounded-md border bg-black/50 px-1 ${selected ? 'border-accent' : 'border-line hover:border-white/30'}`}
              >
                <span className="truncate" style={captionTextStyle({ ...t, size: t.size }, 300)}>
                  {TEMPLATE_INFO[key].sample.split(' ').map((w, i) => (
                    <span key={i} style={i === 1 && t.highlight ? { color: t.highlight } : undefined}>
                      {i > 0 && ' '}
                      {w}
                    </span>
                  ))}
                </span>
                <span className="text-[10px] text-muted">{TEMPLATE_INFO[key].name}</span>
              </button>
            )
          })}
        </div>

        <div className="mt-3 grid grid-cols-2 gap-x-3 gap-y-2.5 text-xs">
          <label className="col-span-2 flex flex-col gap-1">
            <span className="text-muted">Font</span>
            <select
              value={style.font}
              onChange={(e) => save({ ...overrides, font: e.target.value })}
              className="rounded-md border border-line bg-panel-2 px-2 py-1.5 outline-none focus:border-accent"
            >
              {templates.fonts.map((f) => (
                <option key={f} value={f} style={{ fontFamily: f }}>
                  {f}
                </option>
              ))}
            </select>
          </label>
          <label className="col-span-2 flex flex-col gap-1">
            <span className="flex justify-between text-muted">
              Size <span className="text-white/80">{Math.round((style.size / templates.templates[projectStyle.template].size) * 100)}%</span>
            </span>
            <input
              type="range"
              min={Math.round(templates.templates[projectStyle.template].size * 0.6)}
              max={Math.round(templates.templates[projectStyle.template].size * 1.6)}
              value={style.size}
              onChange={(e) => setDraft({ ...overrides, size: Number(e.target.value) })}
              onPointerUp={() => save({ ...overrides, size: style.size })}
              onKeyUp={() => save({ ...overrides, size: style.size })}
              className="accent-[#7c5cff]"
            />
          </label>
          <label className="flex items-center justify-between gap-2">
            <span className="text-muted">Text</span>
            <input type="color" value={style.color} onChange={(e) => save({ ...overrides, color: e.target.value.toUpperCase() })} className="h-7 w-12 cursor-pointer rounded border border-line bg-transparent" />
          </label>
          {style.effect !== 'none' && (
            <label className="flex items-center justify-between gap-2">
              <span className="text-muted">Highlight</span>
              <input
                type="color"
                value={style.highlight || '#FFE600'}
                onChange={(e) => save({ ...overrides, highlight: e.target.value.toUpperCase() })}
                className="h-7 w-12 cursor-pointer rounded border border-line bg-transparent"
              />
            </label>
          )}
          <div className="col-span-2 flex flex-col gap-1">
            <span className="text-muted">Position</span>
            <div className="flex rounded-md border border-line p-0.5">
              {(['top', 'middle', 'bottom'] as const).map((p) => (
                <button
                  key={p}
                  onClick={() => save({ ...overrides, position: p })}
                  className={`flex-1 rounded px-2 py-1 capitalize ${style.position === p ? 'bg-panel-2 text-white' : 'text-muted hover:text-white'}`}
                >
                  {p}
                </button>
              ))}
            </div>
          </div>
          <label className="col-span-2 flex cursor-pointer items-center gap-2">
            <input type="checkbox" checked={style.uppercase} onChange={(e) => save({ ...overrides, uppercase: e.target.checked })} className="accent-[#7c5cff]" />
            ALL CAPS
          </label>
        </div>
        <p className="mt-2 text-[11px] text-muted">The style applies to every clip in this project.</p>
      </section>

      <section>
        <div className="flex items-center justify-between">
          <h4 className="text-xs font-semibold tracking-wide text-muted uppercase">Captions for this clip</h4>
          {captions?.edited && (
            <button onClick={props.onReset} className="text-[11px] text-muted hover:text-white" title="Discard your edits">
              Reset edits
            </button>
          )}
        </div>
        <div className="mt-2 empty:hidden">
          <AnalysisStatus sourceId={sourceId} compact />
        </div>
        {loading && !captions ? (
          <p className="mt-2 text-xs text-muted">Loading…</p>
        ) : captions?.status === 'needs_transcript' ? (
          <div className="mt-2 rounded-md border border-line p-3 text-xs">
            <p className="text-muted">Captions come from the speech in the video, which hasn’t been transcribed yet.</p>
            <div className="mt-2 flex gap-2">
              <select
                value={model}
                onChange={(e) => setModel(e.target.value as SpeechModel)}
                className="rounded-md border border-line bg-panel-2 px-2 py-1.5 outline-none"
                title="Accuracy (the model downloads the first time)"
              >
                {MODELS.map(([m, label]) => (
                  <option key={m} value={m}>
                    {label}
                  </option>
                ))}
              </select>
              <button
                onClick={() => void transcribe(sourceId, model, null)}
                disabled={transcribing}
                className="flex-1 rounded-md bg-accent px-3 py-1.5 font-medium hover:bg-accent-hover disabled:opacity-50"
              >
                {transcribing ? 'Transcribing…' : 'Transcribe speech'}
              </button>
            </div>
          </div>
        ) : captions && captions.cues.length === 0 ? (
          <p className="mt-2 text-xs text-muted">No speech in this clip.</p>
        ) : (
          <ul className="mt-2 flex flex-col gap-1">
            {captions?.cues.map((cue) => (
              <CueRow
                key={`${cue.words[0]?.index}-${cue.start}`}
                cue={cue}
                clipStart={props.clipStart}
                onEdit={(text) => props.onEdit(cue, text)}
                onSeek={() => props.onSeek(cue.start)}
              />
            ))}
          </ul>
        )}
        <p className="mt-3 text-[11px] text-muted">Captions are optional: turn them on in the export settings.</p>
      </section>
    </div>
  )
}
