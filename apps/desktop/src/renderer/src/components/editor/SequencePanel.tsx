import { ArrowDown, ArrowUp, Plus, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import type { AudioAsset, AudioLayer, Clip, ClipSegment } from '../../lib/api'
import { useApp } from '../../store'

const input = 'w-full rounded border border-line bg-panel-2 px-2 py-1 text-xs'
const button = 'inline-flex items-center gap-1 rounded border border-line px-2 py-1 text-xs hover:bg-panel-2 disabled:opacity-40'
const initialSections = (clip: Clip): ClipSegment[] => clip.segments ?? [{ start_ms: clip.start_ms, end_ms: clip.end_ms }]

function Seconds({ label, value, onChange }: { label: string; value: number; onChange(value: number): void }) {
  return <label className="flex min-w-0 flex-1 flex-col gap-1 text-[11px] text-muted">{label}
    <input aria-label={label} type="number" min="0" step="0.1" value={value / 1000}
      onChange={(e) => onChange(Math.round(Number(e.target.value) * 1000))} className={input} />
  </label>
}

function OrderButtons({ index, count, move, remove }: { index: number; count: number; move(delta: number): void; remove(): void }) {
  return <div className="flex gap-1">
    <button className={button} aria-label="Move earlier" disabled={index === 0} onClick={() => move(-1)}><ArrowUp size={12} /></button>
    <button className={button} aria-label="Move later" disabled={index === count - 1} onClick={() => move(1)}><ArrowDown size={12} /></button>
    <button className={button} aria-label="Remove" onClick={remove}><Trash2 size={12} /></button>
  </div>
}

function moved<T>(items: T[], index: number, delta: number): T[] {
  const next = [...items]
  ;[next[index], next[index + delta]] = [next[index + delta], next[index]]
  return next
}

export function SequencePanel({ selected, currentMs, durationMs, outputDurationMs, fps, aspect, onEdit, onSeek }: {
  selected: Clip | null; currentMs: number; durationMs: number; outputDurationMs?: number; fps: number; aspect: string
  onEdit(patch: Partial<Pick<Clip, 'segments' | 'audio'>>): Promise<Clip | null>
  onSeek(ms: number): void
}) {
  const client = useApp((s) => s.client)
  const projectId = useApp((s) => s.openProjectId)
  const clips = useApp((s) => s.clips)
  const sources = useApp((s) => s.sources)
  const [sections, setSections] = useState<ClipSegment[]>(selected ? initialSections(selected) : [])
  const [layers, setLayers] = useState<AudioLayer[]>(selected?.audio ?? [])
  const [assets, setAssets] = useState<AudioAsset[]>([])
  const [order, setOrder] = useState<number[]>([])
  const [choice, setChoice] = useState('')
  const [title, setTitle] = useState('Collage')
  const [resolution, setResolution] = useState(720)
  const [busy, setBusy] = useState(false)
  const [collageId, setCollageId] = useState<number | null>(null)
  const collage = sources.find((s) => s.id === collageId)
  useEffect(() => { setSections(selected ? initialSections(selected) : []); setLayers(selected?.audio ?? []) },
    [selected?.id, JSON.stringify(selected?.segments), JSON.stringify(selected?.audio), selected?.start_ms, selected?.end_ms])
  useEffect(() => {
    let active = true
    if (client && projectId) void client.listAudio(projectId).then((a) => active && setAssets(a)).catch((e) => useApp.getState().setError(String(e)))
    return () => { active = false }
  }, [client, projectId])
  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true)
    try { await fn() } catch (e) { useApp.getState().setError(e instanceof Error ? e.message : String(e)) }
    finally { setBusy(false) }
  }
  const length = sections.reduce((sum, s) => sum + s.end_ms - s.start_ms, 0)
  const invalidSections = sections.length === 0 || sections.some((s) => s.start_ms < 0 || s.end_ms > durationMs || s.end_ms - s.start_ms < 100)
  const addAudio = () => run(async () => {
    if (!client || !projectId) return
    const path = await window.clipping.files.pickAudio()
    if (!path) return
    const asset = await client.importAudio(projectId, path)
    setAssets((prev) => [...prev, asset])
    setLayers((prev) => [...prev, { asset_id: asset.id, start_ms: 0, end_ms: Math.min(asset.duration_ms, outputDurationMs ?? length), offset_ms: 0, volume: 1, original_volume: 1 }])
  })
  const layerEdit = (i: number, patch: Partial<AudioLayer>) => setLayers(layers.map((l, n) => n === i ? { ...l, ...patch } : l))
  return <div className="space-y-6">
    {selected ? <>
      <section className="space-y-2">
        <h4 className="text-sm font-semibold">Sections in this clip</h4>
        <p className="text-xs text-muted">Choose ranges from this video, in playback order. Times are seconds in the source video.</p>
        {sections.map((s, i) => <div key={i} className="space-y-2 rounded border border-line p-2">
          <div className="flex items-center justify-between"><button className="text-xs text-link" onClick={() => onSeek(s.start_ms)}>Section {i + 1}</button>
            <OrderButtons index={i} count={sections.length} move={(d) => setSections(moved(sections, i, d))} remove={() => setSections(sections.filter((_, n) => n !== i))} />
          </div>
          <div className="flex gap-2"><Seconds label="Source start" value={s.start_ms} onChange={(v) => setSections(sections.map((s, n) => n === i ? { ...s, start_ms: v } : s))} />
            <Seconds label="Source end" value={s.end_ms} onChange={(v) => setSections(sections.map((s, n) => n === i ? { ...s, end_ms: v } : s))} /></div>
          <div className="flex gap-1"><button className={button} title="Set section start at the playhead" onClick={() => setSections(sections.map((s, n) => n === i ? { ...s, start_ms: currentMs } : s))}>Start here</button>
            <button className={button} title="Set section end at the playhead" onClick={() => setSections(sections.map((s, n) => n === i ? { ...s, end_ms: Math.min(durationMs, Math.round(currentMs + 1000 / fps)) } : s))}>End here</button></div>
        </div>)}
        <button className={button} disabled={sections.length >= 100} onClick={() => setSections([...sections, { start_ms: Math.min(currentMs, durationMs - 100), end_ms: Math.min(durationMs, currentMs + 5000) }])}><Plus size={12} />Add section at playhead</button>
        <p className="text-xs text-muted">Combined length: {(length / 1000).toFixed(2)} s{selected.tighten ? ' before Tighten' : ''}</p>
        {invalidSections && <p className="text-xs text-warning">Each section must be at least 0.1 s and fit inside the video.</p>}
        <button className={button} disabled={busy || invalidSections} onClick={() => void run(() => onEdit({ segments: sections }))}>Save sections</button>
      </section>
      <section className="space-y-2">
        <h4 className="text-sm font-semibold">Additional sound</h4>
        <p className="text-xs text-muted">Place sound on the assembled output. Start/end are seconds from the beginning of this clip, after cuts. Save sections first.</p>
        {layers.map((l, i) => <div key={i} className="space-y-2 rounded border border-line p-2">
          <div className="flex items-center justify-between gap-2"><span className="truncate text-xs">{assets.find((a) => a.id === l.asset_id)?.name ?? 'Audio'}</span><button className={button} aria-label="Remove audio" onClick={() => setLayers(layers.filter((_, n) => n !== i))}><Trash2 size={12} /></button></div>
          <div className="flex gap-2"><Seconds label="Clip start" value={l.start_ms} onChange={(v) => layerEdit(i, { start_ms: v })} /><Seconds label="Clip end" value={l.end_ms} onChange={(v) => layerEdit(i, { end_ms: v })} /></div>
          <Seconds label="Audio file offset" value={l.offset_ms} onChange={(v) => layerEdit(i, { offset_ms: v })} />
          <label className="block text-xs text-muted">Added sound: {Math.round(l.volume * 100)}%<input aria-label="Added sound volume" className="w-full" type="range" min="0" max="1" step="0.05" value={l.volume} onChange={(e) => layerEdit(i, { volume: Number(e.target.value) })} /></label>
          <label className="block text-xs text-muted">Original sound in this section: {Math.round(l.original_volume * 100)}%<input aria-label="Original sound volume" className="w-full" type="range" min="0" max="1" step="0.05" value={l.original_volume} onChange={(e) => layerEdit(i, { original_volume: Number(e.target.value) })} /></label>
        </div>)}
        <div className="flex gap-2"><button className={button} disabled={busy || layers.length >= 20} onClick={() => void addAudio()}>Add audio file</button>
          <button className={button} disabled={busy} onClick={() => void run(() => onEdit({ audio: layers }))}>Save sound</button></div>
      </section>
    </> : <p className="text-xs text-muted">Select a clip to combine ranges or add sound.</p>}
    <section className="space-y-2 border-t border-line pt-4">
      <h4 className="text-sm font-semibold">Collage · join clips</h4>
      <p className="text-xs text-muted">Join project clips in this order into a new editable video. Uses each clip’s saved framing, sections and sound at {aspect}, {resolution}p and 30 fps.</p>
      <input className={input} aria-label="Collage title" value={title} onChange={(e) => setTitle(e.target.value)} />
      <label className="block space-y-1 text-xs text-muted"><span>Collage resolution</span><select className={input} aria-label="Collage resolution" value={resolution} onChange={(e) => setResolution(Number(e.target.value))}><option value={720}>720p · faster</option><option value={1080}>1080p · higher quality</option></select></label>
      <select className={input} aria-label="Choose collage clip" value={choice} onChange={(e) => setChoice(e.target.value)}><option value="">Choose a project clip</option>
        {clips.map((c) => <option key={c.id} value={c.id}>{c.title} · {sources.find((s) => s.id === c.source_id)?.title}</option>)}
      </select>
      <button className={button} disabled={!choice || order.length >= 100} onClick={() => setOrder([...order, Number(choice)])}>Append clip</button>
      {order.map((id, i) => <div key={i} className="flex items-center justify-between gap-1"><span className="min-w-0 truncate text-xs">{i + 1}. {clips.find((c) => c.id === id)?.title ?? 'Deleted clip'}</span>
        <OrderButtons index={i} count={order.length} move={(d) => setOrder(moved(order, i, d))} remove={() => setOrder(order.filter((_, n) => n !== i))} /></div>)}
      <button className={button} disabled={busy || order.length < 2 || !title.trim() || !!collage && ['queued', 'processing', 'probing'].includes(collage.status)} onClick={() => void run(async () => {
        if (!client || !projectId) return
        const source = await client.createCollage(projectId, order, title, aspect, resolution)
        setCollageId(source.id)
        await useApp.getState().refresh()
      })}>Create single clip</button>
      {collage && <div className="space-y-2 text-xs text-muted"><p>{collage.title}: {collage.status} · {Math.round(collage.progress * 100)}%{collage.error ? ` · ${collage.error}` : ''}</p>
        {collage.status === 'ready' ? <button className={button} onClick={async () => { await useApp.getState().refresh(); useApp.getState().openEditor(collage.id) }}>Open collage in editor</button>
          : ['failed', 'cancelled'].includes(collage.status) ? <button className={button} onClick={() => void run(async () => { await client?.retrySource(collage.id) })}>Retry</button>
            : <button className={button} onClick={() => void run(async () => { await client?.cancelSource(collage.id) })}>Cancel collage</button>}
      </div>}
    </section>
  </div>
}
