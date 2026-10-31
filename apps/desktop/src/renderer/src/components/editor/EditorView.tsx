import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  DEFAULT_FIT,
  type CaptionCue,
  type Clip,
  type ClipCaptions,
  type Crop,
  type CutPlan,
  type FitStyle,
  type FollowMode,
  type FramingMode
} from '../../lib/api'
import { CaptionsPanel } from './CaptionsPanel'
import { aspectRatio, cropAt, defaultCrop } from '../../lib/aspects'
import { frameToMs, msToFrame, timecode } from '../../lib/time'
import { useApp } from '../../store'
import { ClipPanel } from './ClipPanel'
import { Stage } from './Stage'
import { Timeline, type Range } from './Timeline'

const DEFAULT_CLIP_MS = 15_000
const PLAYBACK_RATES = [1, 2, 4]

interface HistoryEntry {
  undo(): Promise<unknown>
  redo(): Promise<unknown>
}

const isTyping = (target: EventTarget | null): boolean =>
  target instanceof HTMLElement && (target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName))

export function EditorView() {
  const sourceId = useApp((s) => s.editorSourceId)
  const source = useApp((s) => s.sources.find((x) => x.id === s.editorSourceId))
  const allClips = useApp((s) => s.clips)
  const client = useApp((s) => s.client)
  const analysisDone = useApp((s) => s.analyses[s.editorSourceId ?? -1]?.status === 'done')
  const { closeEditor, createClip, updateClip, setClipFormat, deleteClip, openExportDialog, openAutoClipDialog, replaceClip, setError } =
    useApp.getState()

  const clips = useMemo(() => allClips.filter((c) => c.source_id === sourceId), [allClips, sourceId])
  const fps = source?.fps ?? 30
  const durationMs = source?.duration_ms ?? 0
  const totalFrames = Math.max(1, msToFrame(durationMs, fps))
  const srcAspect = source?.width && source?.height ? source.width / source.height : 16 / 9

  const videoRef = useRef<HTMLVideoElement | null>(null)
  const [frame, setFrame] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [rate, setRate] = useState(1)
  const [muted, setMuted] = useState(false)
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [draft, setDraft] = useState<Range | null>(null)
  const [dragRange, setDragRange] = useState<Range | null>(null)
  const [dragCrop, setDragCrop] = useState<Crop | null>(null)
  const [aspect, setAspect] = useState('9:16')
  const [view, setView] = useState<'edit' | 'preview'>('edit')
  const [waveform, setWaveform] = useState<Uint8Array | null>(null)
  const [tracking, setTracking] = useState(false)
  const [fitDraft, setFitDraft] = useState<FitStyle | null>(null)
  const undoStack = useRef<HistoryEntry[]>([])
  const redoStack = useRef<HistoryEntry[]>([])

  const selected = clips.find((c) => c.id === selectedId) ?? null
  const currentMs = frameToMs(frame, fps)
  const range: Range | null = dragRange ?? (selected ? { start: selected.start_ms, end: selected.end_ms } : draft)
  const format = selected?.formats[aspect]
  const mode: FramingMode = format?.mode ?? 'manual'
  const centered = defaultCrop(aspect, source?.width ?? 16, source?.height ?? 9)
  // Smart framing shows where the crop is at the playhead, so it moves as the video plays.
  const crop =
    dragCrop ?? (mode === 'smart' && format?.keyframes?.length ? cropAt(format.keyframes, currentMs) : (format?.crop ?? centered))
  const fit: FitStyle = fitDraft ?? { ...DEFAULT_FIT, ...(mode === 'fit' ? format?.options : {}) }

  useEffect(() => setFitDraft(null), [selectedId, aspect])

  // Captions for the selected clip; refetched when the clip's range, the transcript or the style changes.
  const captionsVersion = useApp((s) => s.captionsVersion)
  const [captions, setCaptions] = useState<ClipCaptions | null>(null)
  const [captionsLoading, setCaptionsLoading] = useState(false)
  const [showCaptions, setShowCaptions] = useState(true)
  useEffect(() => {
    setCaptions(null)
    if (!client || !selected) return
    let cancelled = false
    setCaptionsLoading(true)
    client
      .getCaptions(selected.id)
      .then((c) => !cancelled && setCaptions(c))
      .catch(() => !cancelled && setCaptions(null))
      .finally(() => !cancelled && setCaptionsLoading(false))
    return () => {
      cancelled = true
    }
  }, [client, selected?.id, selected?.start_ms, selected?.end_ms, captionsVersion])

  // What Tighten removes from the selected clip; playback jumps over those parts.
  const [cutPlan, setCutPlan] = useState<CutPlan | null>(null)
  const cutsRef = useRef<{ start: number; end: number }[]>([])
  useEffect(() => {
    setCutPlan(null)
    cutsRef.current = []
    if (!client || !selected?.tighten) return
    let cancelled = false
    client
      .getCutPlan(selected.id)
      .then((plan) => {
        if (cancelled) return
        setCutPlan(plan)
        cutsRef.current = plan.cuts ?? []
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [client, selected?.id, selected?.start_ms, selected?.end_ms, JSON.stringify(selected?.tighten), captionsVersion])

  const editCaption = async (cue: CaptionCue, text: string) => {
    if (!client || !selected) return
    try {
      setCaptions(await client.editCaption(selected.id, cue.words.map((w) => w.index), text))
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }

  useEffect(() => {
    if (!client || !source?.timeline) return
    let cancelled = false
    client
      .waveform(source.timeline.waveform_url)
      .then((data) => !cancelled && setWaveform(data))
      .catch(() => !cancelled && setWaveform(null))
    return () => {
      cancelled = true
    }
  }, [client, source?.timeline])

  // Track the displayed frame precisely while playing.
  useEffect(() => {
    const video = videoRef.current
    if (!video) return
    let handle = 0
    const onFrame: VideoFrameRequestCallback = (_now, meta) => {
      const ms = meta.mediaTime * 1000
      // Preview the tightened clip: jump over removed fillers and pauses while playing.
      const cut = !video.paused ? cutsRef.current.find((c) => ms >= c.start && ms < c.end - 15) : undefined
      if (cut) video.currentTime = cut.end / 1000 + 0.001
      setFrame(Math.min(totalFrames - 1, Math.floor(meta.mediaTime * fps + 1e-3)))
      handle = video.requestVideoFrameCallback(onFrame)
    }
    handle = video.requestVideoFrameCallback(onFrame)
    const onPlay = () => setPlaying(true)
    const onPause = () => setPlaying(false)
    video.addEventListener('play', onPlay)
    video.addEventListener('pause', onPause)
    return () => {
      video.cancelVideoFrameCallback(handle)
      video.removeEventListener('play', onPlay)
      video.removeEventListener('pause', onPause)
    }
  }, [fps, totalFrames, source?.proxy_url])

  useEffect(() => {
    if (videoRef.current) videoRef.current.muted = muted
  }, [muted])

  const seekFrame = useCallback(
    (n: number) => {
      const target = Math.min(totalFrames - 1, Math.max(0, n))
      setFrame(target)
      // Aim for the middle of the frame so float rounding can't land on the previous one.
      if (videoRef.current) videoRef.current.currentTime = (target + 0.5) / fps
    },
    [fps, totalFrames]
  )
  const seekMs = useCallback((ms: number) => seekFrame(msToFrame(ms, fps)), [fps, seekFrame])

  const togglePlay = useCallback(() => {
    const video = videoRef.current
    if (!video) return
    if (video.paused) {
      video.playbackRate = 1
      setRate(1)
      void video.play()
    } else video.pause()
  }, [])

  const pushHistory = (entry: HistoryEntry) => {
    undoStack.current.push(entry)
    if (undoStack.current.length > 100) undoStack.current.shift()
    redoStack.current = []
  }

  const commitRange = useCallback(
    async (clip: Clip, next: Range) => {
      const before = { start_ms: clip.start_ms, end_ms: clip.end_ms }
      const after = { start_ms: next.start, end_ms: next.end }
      if (before.start_ms === after.start_ms && before.end_ms === after.end_ms) return
      const saved = await updateClip(clip.id, after)
      if (saved) pushHistory({ undo: () => updateClip(clip.id, before), redo: () => updateClip(clip.id, after) })
      // Trimmed past the part that was tracked: follow faces over the new range too.
      const fmt = saved?.formats[aspect]
      if (saved && fmt?.mode === 'smart' && fmt.stale) {
        setTracking(true)
        await setClipFormat(saved.id, aspect, 'smart', null, undefined, fmt.options.follow ?? 'speaker')
        setTracking(false)
      }
    },
    [updateClip, setClipFormat, aspect]
  )

  /** Change a clip's framing for the current size, with undo. Smart mode runs face tracking (a few seconds). */
  const commitFormat = async (clip: Clip, nextMode: FramingMode, nextCrop: Crop | null, nextFit?: FitStyle, follow?: FollowMode) => {
    const prev = clip.formats[aspect]
    const beforeMode: FramingMode = prev?.mode ?? 'manual'
    const beforeCrop = prev?.mode === 'manual' && prev.crop ? prev.crop : centered
    const beforeFit = prev?.mode === 'fit' ? { ...DEFAULT_FIT, ...prev.options } : undefined
    if (nextMode === 'smart') setTracking(true)
    const nextFollow = nextMode === 'smart' ? (follow ?? prev?.options.follow ?? 'speaker') : undefined
    const saved = await setClipFormat(clip.id, aspect, nextMode, nextCrop, nextFit, nextFollow)
    setTracking(false)
    if (saved) {
      const a = aspect
      pushHistory({
        undo: () => setClipFormat(clip.id, a, beforeMode, beforeMode === 'manual' ? beforeCrop : null, beforeFit),
        redo: () => setClipFormat(clip.id, a, nextMode, nextCrop, nextFit)
      })
    }
  }

  const onRangeChange = async (next: Range, final: boolean) => {
    if (!selected) {
      setDraft(next)
      return
    }
    if (!final) {
      setDragRange(next)
      return
    }
    await commitRange(selected, next)
    setDragRange(null)
  }

  const onCropChange = async (next: Crop, final: boolean) => {
    if (!selected) return
    if (!final) {
      setDragCrop(next)
      return
    }
    // Dragging a smart crop switches to a fixed crop where you dropped it.
    await commitFormat(selected, 'manual', next)
    setDragCrop(null)
  }

  /** Mark In / Out at the current frame. Out includes the frame you're looking at. */
  const mark = (edge: 'in' | 'out') => {
    const current = range
    let next: Range
    if (edge === 'in') {
      const start = currentMs
      next = current && start < current.end - 1000 / fps ? { start, end: current.end } : { start, end: Math.min(durationMs, start + DEFAULT_CLIP_MS) }
    } else {
      const end = Math.min(durationMs, frameToMs(frame + 1, fps))
      next = current && end > current.start + 1000 / fps ? { start: current.start, end } : { start: Math.max(0, end - DEFAULT_CLIP_MS), end }
    }
    if (selected) void commitRange(selected, next)
    else setDraft(next)
  }

  const addClip = async () => {
    const r = draft ?? { start: currentMs, end: Math.min(durationMs, currentMs + DEFAULT_CLIP_MS) }
    if (r.end - r.start < 100) {
      setError('Move the playhead earlier: there is less than 0.1 s left in the video.')
      return
    }
    if (!sourceId) return
    const clip = await createClip(sourceId, r.start, r.end)
    if (clip) {
      setDraft(null)
      setSelectedId(clip.id)
    }
  }

  const select = (id: number | null) => {
    setSelectedId(id)
    setDragRange(null)
    setDragCrop(null)
    const clip = clips.find((c) => c.id === id)
    if (clip) {
      setDraft(null)
      seekMs(clip.start_ms)
    }
  }

  const nudge = (edge: 'start' | 'end', frames: number) => {
    if (!selected || !range) return
    const delta = frameToMs(frames, fps)
    const next = edge === 'start' ? { ...range, start: range.start + delta } : { ...range, end: range.end + delta }
    if (next.start < 0 || next.end > durationMs || next.end - next.start < 100) return
    void commitRange(selected, next)
    seekMs(edge === 'start' ? next.start : next.end - 1000 / fps)
  }

  const removeSelected = async () => {
    if (selected && confirm(`Delete "${selected.title}"?`)) {
      await deleteClip(selected.id)
      setSelectedId(null)
    }
  }

  const undo = async () => {
    const entry = undoStack.current.pop()
    if (entry) {
      await entry.undo()
      redoStack.current.push(entry)
    }
  }
  const redo = async () => {
    const entry = redoStack.current.pop()
    if (entry) {
      await entry.redo()
      undoStack.current.push(entry)
    }
  }

  // Keyboard shortcuts. Re-bound each render so handlers see current state.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isTyping(e.target) || e.altKey) return
      const video = videoRef.current
      const ctrl = e.ctrlKey || e.metaKey
      const key = e.key.toLowerCase()
      let handled = true
      if (ctrl && key === 'z' && !e.shiftKey) void undo()
      else if (ctrl && (key === 'y' || (key === 'z' && e.shiftKey))) void redo()
      else if (ctrl) handled = false
      else if (key === ' ') togglePlay()
      else if (key === 'k') video?.pause()
      else if (key === 'l' && video) {
        const next = video.paused ? 1 : PLAYBACK_RATES[Math.min(PLAYBACK_RATES.indexOf(rate) + 1, PLAYBACK_RATES.length - 1)]
        video.playbackRate = next
        setRate(next)
        void video.play()
      } else if (key === 'j') seekFrame(frame - Math.round(fps))
      else if (key === 'arrowleft') seekFrame(frame - (e.shiftKey ? Math.round(fps) : 1))
      else if (key === 'arrowright') seekFrame(frame + (e.shiftKey ? Math.round(fps) : 1))
      else if (key === 'home') seekMs(range?.start ?? 0)
      else if (key === 'end') seekMs(range ? range.end - 1000 / fps : durationMs)
      else if (key === 'i') mark('in')
      else if (key === 'o') mark('out')
      else if (key === 'n' || key === 'enter') void addClip()
      else if (key === 'delete' || key === 'backspace') void removeSelected()
      else if (key === 'escape') select(null)
      else if (key === 'p') setView((v) => (v === 'edit' ? 'preview' : 'edit'))
      else handled = false
      if (handled) e.preventDefault()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  if (!source || !client || !source.proxy_url) {
    return <div className="grid h-full place-items-center text-sm text-muted">This video isn’t ready for editing.</div>
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center gap-3 border-b border-line px-4 py-2">
        <button onClick={closeEditor} className="rounded-md border border-line px-2.5 py-1 text-xs text-muted hover:bg-panel-2">
          ← Back
        </button>
        <h2 className="min-w-0 flex-1 truncate text-sm font-semibold">{source.title}</h2>
        <ShortcutsHint />
        <button
          onClick={() => openExportDialog(clips.map((c) => c.id))}
          disabled={clips.length === 0}
          className="rounded-md bg-accent px-3 py-1.5 text-xs font-medium hover:bg-accent-hover disabled:opacity-50"
        >
          Export clips…
        </button>
      </div>

      <div className="flex min-h-0 flex-1">
        <div className="flex min-w-0 flex-1 flex-col">
          <Stage
            videoRef={videoRef}
            src={client.mediaUrl(source.proxy_url)}
            poster={source.poster_url ? client.mediaUrl(source.poster_url) : undefined}
            srcAspect={srcAspect}
            targetRatio={aspectRatio(aspect)}
            mode={mode}
            crop={crop}
            fit={fit}
            captions={showCaptions && captions?.status === 'ready' ? captions : null}
            timeMs={currentMs}
            view={view}
            editable={selected !== null && !tracking}
            onCropChange={(c, final) => void onCropChange(c, final)}
            onTogglePlay={togglePlay}
          />
          <div className="flex items-center gap-2 border-t border-line bg-panel px-3 py-2 text-xs">
            <button onClick={() => seekFrame(frame - 1)} className="rounded px-2 py-1 hover:bg-panel-2" title="Previous frame (←)">
              ⏮
            </button>
            <button onClick={togglePlay} className="w-16 rounded bg-panel-2 px-2 py-1 hover:bg-line" title="Play / pause (Space)">
              {playing ? 'Pause' : 'Play'}
            </button>
            <button onClick={() => seekFrame(frame + 1)} className="rounded px-2 py-1 hover:bg-panel-2" title="Next frame (→)">
              ⏭
            </button>
            <span className="ml-2 font-mono text-[13px]">{timecode(currentMs, fps)}</span>
            <span className="text-muted">/ {timecode(durationMs, fps)}</span>
            <span className="text-muted">· frame {frame}</span>
            {rate !== 1 && <span className="rounded bg-accent/30 px-1.5">{rate}×</span>}
            <span className="flex-1" />
            <button onClick={() => mark('in')} className="rounded border border-line px-2 py-1 hover:bg-panel-2" title="Mark In (I)">
              Mark In
            </button>
            <button onClick={() => mark('out')} className="rounded border border-line px-2 py-1 hover:bg-panel-2" title="Mark Out (O)">
              Mark Out
            </button>
            <button onClick={() => setMuted((m) => !m)} className="rounded px-2 py-1 text-muted hover:bg-panel-2">
              {muted ? 'Unmute' : 'Mute'}
            </button>
            <div className="ml-1 flex rounded-md border border-line p-0.5">
              {(['edit', 'preview'] as const).map((v) => (
                <button
                  key={v}
                  onClick={() => setView(v)}
                  title="Toggle with P"
                  className={`rounded px-2 py-1 ${view === v ? 'bg-panel-2 text-white' : 'text-muted hover:text-white'}`}
                >
                  {v === 'edit' ? 'Edit framing' : 'Preview output'}
                </button>
              ))}
            </div>
          </div>
        </div>

        <ClipPanel
          captionsTab={
            selected && (
              <CaptionsPanel
                sourceId={source.id}
                clipStart={selected.start_ms}
                captions={captions}
                loading={captionsLoading}
                showOverlay={showCaptions}
                onShowOverlay={(show) => {
                  setShowCaptions(show)
                  if (show) setView('preview')
                }}
                onEdit={(cue, text) => void editCaption(cue, text)}
                onReset={async () => client && setCaptions(await client.resetCaptions(selected.id))}
                // Round up to the first frame inside the cue, so the caption you clicked is the one showing.
                onSeek={(ms) => seekFrame(Math.ceil((ms * fps) / 1000))}
              />
            )
          }
          sourceId={source.id}
          canReplace={analysisDone}
          onAutoClip={() => openAutoClipDialog(source.id, draft)}
          onReplace={async () => {
            if (!selected) return
            const next = await replaceClip(selected.id)
            if (next) select(next.id)
          }}
          clips={clips}
          selected={selected}
          range={range}
          fps={fps}
          aspect={aspect}
          mode={mode}
          smart={mode === 'smart' ? (format?.options ?? null) : null}
          onFollow={(f) => selected && void commitFormat(selected, 'smart', null, undefined, f)}
          tighten={selected?.tighten ?? null}
          cutPlan={cutPlan}
          onTighten={(t) => selected && void updateClip(selected.id, { tighten: t })}
          tracking={tracking}
          faceRatio={mode === 'smart' ? (format?.options.face_ratio ?? null) : null}
          stale={mode === 'smart' && !!format?.stale}
          fit={fit}
          onRetrack={() => selected && void commitFormat(selected, 'smart', null)}
          onFitChange={setFitDraft}
          onFitCommit={async (style) => {
            setFitDraft(style)
            if (selected) await commitFormat(selected, 'fit', null, style)
            setFitDraft(null)
          }}
          onSelect={select}
          onAdd={() => void addClip()}
          onAspect={setAspect}
          onMode={(m) =>
            selected &&
            m !== mode &&
            void commitFormat(selected, m, m === 'manual' ? crop : null, m === 'fit' ? { ...DEFAULT_FIT } : undefined)
          }
          onResetCrop={() => selected && void commitFormat(selected, 'manual', centered)}
          onNudge={nudge}
          onTitle={(title) => selected && void updateClip(selected.id, { title })}
          onDelete={() => void removeSelected()}
        />
      </div>

      <Timeline
        durationMs={durationMs}
        fps={fps}
        timeline={source.timeline}
        thumbsSrc={source.timeline ? client.mediaUrl(source.timeline.thumbs_url) : null}
        waveform={waveform}
        clips={clips}
        selectedId={selectedId}
        range={range}
        currentMs={currentMs}
        playing={playing}
        cuts={cutPlan?.cuts ?? []}
        onSeek={seekMs}
        onRangeChange={(r, final) => void onRangeChange(r, final)}
        onSelect={select}
      />
    </div>
  )
}

const SHORTCUTS: [string, string][] = [
  ['Space / K', 'Play / pause'],
  ['L', 'Play, press again for 2× / 4×'],
  ['J', 'Back 1 second'],
  ['← / →', 'Previous / next frame'],
  ['Shift + ← / →', 'Back / forward 1 second'],
  ['I / O', 'Mark In / Out'],
  ['N or Enter', 'Add clip'],
  ['Home / End', 'Go to clip start / end'],
  ['P', 'Toggle output preview'],
  ['Delete', 'Delete selected clip'],
  ['Esc', 'Deselect clip'],
  ['Ctrl + Z / Ctrl + Y', 'Undo / redo'],
  ['Ctrl + wheel', 'Zoom timeline']
]

function ShortcutsHint() {
  const [open, setOpen] = useState(false)
  return (
    <div className="relative">
      <button onClick={() => setOpen((o) => !o)} className="rounded-md px-2.5 py-1 text-xs text-muted hover:bg-panel-2">
        Shortcuts
      </button>
      {open && (
        <div className="absolute top-full right-0 z-40 mt-1 w-72 rounded-lg border border-line bg-panel-2 p-3 shadow-xl">
          <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1.5 text-xs">
            {SHORTCUTS.map(([keys, what]) => (
              <div key={keys} className="contents">
                <dt className="font-mono text-white">{keys}</dt>
                <dd className="text-muted">{what}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}
    </div>
  )
}
