import { useCallback, useEffect, useLayoutEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import type { Clip, SourceTimeline } from '../../lib/api'
import { snapMs, timecode } from '../../lib/time'

export interface Range {
  start: number
  end: number
}

interface Props {
  durationMs: number
  fps: number
  timeline: SourceTimeline | null
  thumbsSrc: string | null
  waveform: Uint8Array | null
  clips: Clip[]
  selectedId: number | null
  /** Range being edited: the selected clip's, or the draft for a new clip. */
  range: Range | null
  currentMs: number
  playing: boolean
  /** Parts Tighten removes from the selected clip (source ms). */
  cuts?: { start: number; end: number; reason: string }[]
  onSeek(ms: number): void
  onRangeChange(range: Range, final: boolean): void
  onSelect(id: number | null): void
}

const RULER_H = 22
const THUMBS_H = 48
const WAVE_H = 44
const CLIPS_H = 26
const TOTAL_H = RULER_H + THUMBS_H + WAVE_H + CLIPS_H
const TICK_STEPS = [0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30, 60, 120, 300, 600, 900, 1800, 3600]
const MAX_PX_PER_FRAME = 16

type DragState =
  | { kind: 'seek' }
  | { kind: 'start' | 'end'; range: Range; last: Range }
  | { kind: 'move'; range: Range; last: Range; originX: number; moved: boolean }

export function Timeline(props: Props) {
  const { durationMs, fps, timeline, thumbsSrc, waveform, clips, selectedId, range, currentMs, playing } = props
  const scrollRef = useRef<HTMLDivElement>(null)
  const innerRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const drag = useRef<DragState | null>(null)
  const [viewW, setViewW] = useState(0)
  const [scrollLeft, setScrollLeft] = useState(0)
  const [zoomPps, setZoomPps] = useState<number | null>(null) // null = fit whole video

  const durationS = Math.max(durationMs / 1000, 0.001)
  const fitPps = viewW > 0 ? viewW / durationS : 1
  const maxPps = Math.max(fitPps, fps * MAX_PX_PER_FRAME)
  const pps = Math.min(maxPps, Math.max(fitPps, zoomPps ?? fitPps))
  const contentW = durationS * pps
  const minLenMs = Math.max(100, 1000 / fps)

  const xFor = (ms: number): number => (ms / 1000) * pps

  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const observer = new ResizeObserver(([entry]) => setViewW(entry.contentRect.width))
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  // Zoom keeps the time under the cursor (or the playhead) in place.
  const zoomTo = useCallback(
    (nextPps: number, anchorClientX?: number) => {
      const el = scrollRef.current
      if (!el) return
      const clamped = Math.min(maxPps, Math.max(fitPps, nextPps))
      const anchorX =
        anchorClientX !== undefined
          ? anchorClientX - el.getBoundingClientRect().left
          : Math.min(Math.max(xFor(currentMs) - el.scrollLeft, 0), el.clientWidth)
      const t = (el.scrollLeft + anchorX) / pps
      setZoomPps(clamped <= fitPps * 1.001 ? null : clamped)
      requestAnimationFrame(() => {
        el.scrollLeft = t * clamped - anchorX
        setScrollLeft(el.scrollLeft)
      })
    },
    [maxPps, fitPps, pps, currentMs]
  )

  // Wheel: Ctrl zooms, otherwise scrolls sideways. Needs a non-passive listener to stop page scroll.
  useEffect(() => {
    const el = scrollRef.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      if (e.ctrlKey || e.metaKey) zoomTo(pps * (e.deltaY < 0 ? 1.25 : 0.8), e.clientX)
      else el.scrollLeft += e.deltaY + e.deltaX
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [zoomTo, pps])

  // Keep the playhead in view while playing.
  useLayoutEffect(() => {
    const el = scrollRef.current
    if (!el || !playing) return
    const x = xFor(currentMs)
    if (x < el.scrollLeft || x > el.scrollLeft + el.clientWidth - 40) el.scrollLeft = x - el.clientWidth * 0.1
  }, [currentMs, playing])

  // Waveform: drawn only for the visible part, at device resolution.
  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas || viewW === 0) return
    const dpr = window.devicePixelRatio || 1
    canvas.width = Math.round(viewW * dpr)
    canvas.height = Math.round(WAVE_H * dpr)
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    ctx.scale(dpr, dpr)
    ctx.clearRect(0, 0, viewW, WAVE_H)
    if (!waveform || waveform.length === 0 || !timeline) return
    const perSecond = timeline.peaks_per_second
    const mid = WAVE_H / 2
    ctx.fillStyle = '#7c5cff'
    for (let x = 0; x < viewW; x++) {
      const t0 = (scrollLeft + x) / pps
      const t1 = (scrollLeft + x + 1) / pps
      const i0 = Math.floor(t0 * perSecond)
      const i1 = Math.max(i0 + 1, Math.floor(t1 * perSecond))
      let peak = 0
      for (let i = i0; i < i1 && i < waveform.length; i++) peak = Math.max(peak, waveform[i])
      const h = Math.max(1, (peak / 255) * (WAVE_H - 6))
      ctx.fillRect(x, mid - h / 2, 1, h)
    }
  }, [waveform, timeline, viewW, scrollLeft, pps])

  const msAt = (clientX: number): number => {
    const left = innerRef.current?.getBoundingClientRect().left ?? 0
    const ms = ((clientX - left) / pps) * 1000
    return Math.min(durationMs, Math.max(0, snapMs(ms, fps)))
  }

  const capture = (e: ReactPointerEvent) => {
    e.preventDefault()
    e.stopPropagation()
    ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)
  }

  const beginSeek = (e: ReactPointerEvent) => {
    capture(e)
    drag.current = { kind: 'seek' }
    props.onSeek(msAt(e.clientX))
  }

  const beginHandle = (kind: 'start' | 'end') => (e: ReactPointerEvent) => {
    if (!range) return
    capture(e)
    drag.current = { kind, range, last: range }
  }

  const beginMove = (e: ReactPointerEvent) => {
    if (!range) return
    capture(e)
    drag.current = { kind: 'move', range, last: range, originX: e.clientX, moved: false }
  }

  const onMove = (e: ReactPointerEvent) => {
    const d = drag.current
    if (!d) return
    if (d.kind === 'seek') {
      props.onSeek(msAt(e.clientX))
      return
    }
    let next: Range
    if (d.kind !== 'move') {
      next =
        d.kind === 'start'
          ? { start: Math.min(msAt(e.clientX), d.range.end - minLenMs), end: d.range.end }
          : { start: d.range.start, end: Math.max(msAt(e.clientX), d.range.start + minLenMs) }
    } else {
      if (Math.abs(e.clientX - d.originX) > 3) d.moved = true
      if (!d.moved) return
      const len = d.range.end - d.range.start
      const delta = ((e.clientX - d.originX) / pps) * 1000
      const start = Math.min(durationMs - len, Math.max(0, snapMs(d.range.start + delta, fps)))
      next = { start, end: start + len }
    }
    next = { start: Math.max(0, next.start), end: Math.min(durationMs, next.end) }
    d.last = next
    props.onRangeChange(next, false)
  }

  const onUp = () => {
    const d = drag.current
    drag.current = null
    if (d && d.kind !== 'seek' && d.last !== d.range) props.onRangeChange(d.last, true)
  }

  // --- rendering helpers ---

  const tickStep = TICK_STEPS.find((s) => s * pps >= 90) ?? TICK_STEPS[TICK_STEPS.length - 1]
  const visibleStart = scrollLeft / pps
  const visibleEnd = (scrollLeft + viewW) / pps
  const ticks: number[] = []
  for (let t = Math.floor(visibleStart / tickStep) * tickStep; t <= visibleEnd; t += tickStep) {
    if (t >= 0 && t <= durationS) ticks.push(t)
  }

  const thumbs = timeline?.thumbs
  const tiles: { x: number; w: number; index: number }[] = []
  if (thumbs && thumbsSrc) {
    const tileW = (THUMBS_H * thumbs.tile_w) / thumbs.tile_h
    const first = Math.max(0, Math.floor(scrollLeft / tileW))
    const last = Math.min(Math.ceil(contentW / tileW), Math.ceil((scrollLeft + viewW) / tileW))
    for (let i = first; i <= last; i++) {
      const t = ((i + 0.5) * tileW) / pps
      tiles.push({ x: i * tileW, w: tileW, index: Math.min(thumbs.count - 1, Math.floor(t / thumbs.interval_s)) })
    }
  }
  const tileScale = thumbs ? THUMBS_H / thumbs.tile_h : 1

  const handle = (kind: 'start' | 'end', ms: number) => (
    <div
      onPointerDown={beginHandle(kind)}
      onPointerMove={onMove}
      onPointerUp={onUp}
      title={kind === 'start' ? 'Drag to set the start' : 'Drag to set the end'}
      className="group absolute z-20 w-3 cursor-ew-resize"
      style={{ left: xFor(ms) - (kind === 'start' ? 0 : 12), top: RULER_H, height: TOTAL_H - RULER_H }}
    >
      <div
        className={`absolute inset-y-0 w-1.5 bg-amber-400 group-hover:bg-amber-300 ${kind === 'start' ? 'left-0 rounded-l' : 'right-0 rounded-r'}`}
      />
    </div>
  )

  return (
    <div className="border-t border-line bg-panel">
      <div className="flex items-center justify-between px-3 py-1.5 text-xs text-muted">
        <span>
          {range
            ? `In ${timecode(range.start, fps)} · Out ${timecode(range.end, fps)} · ${((range.end - range.start) / 1000).toFixed(2)}s`
            : 'Press I and O to mark a range, or drag on the timeline'}
        </span>
        <div className="flex items-center gap-1">
          <button onClick={() => zoomTo(pps * 0.66)} className="rounded px-2 py-0.5 hover:bg-panel-2" title="Zoom out (−)">
            −
          </button>
          <button onClick={() => setZoomPps(null)} className="rounded px-2 py-0.5 hover:bg-panel-2" title="Fit whole video">
            Fit
          </button>
          <button onClick={() => zoomTo(pps * 1.5)} className="rounded px-2 py-0.5 hover:bg-panel-2" title="Zoom in (+)">
            +
          </button>
        </div>
      </div>

      <div
        ref={scrollRef}
        onScroll={(e) => setScrollLeft(e.currentTarget.scrollLeft)}
        className="timeline-scroll relative overflow-x-auto overflow-y-hidden select-none"
        style={{ height: TOTAL_H + 12 }}
      >
        <div ref={innerRef} className="relative" style={{ width: contentW, height: TOTAL_H }}>
          {/* Ruler */}
          <div
            onPointerDown={beginSeek}
            onPointerMove={onMove}
            onPointerUp={onUp}
            className="absolute inset-x-0 top-0 cursor-pointer border-b border-line"
            style={{ height: RULER_H }}
          >
            {ticks.map((t) => (
              <div key={t} className="absolute top-0 h-full border-l border-line pl-1 text-[10px] text-muted" style={{ left: t * pps }}>
                {tickStep < 1 ? timecode(t * 1000, fps) : timecode(t * 1000, fps).replace(/\.\d+$/, '')}
              </div>
            ))}
          </div>

          {/* Thumbnails + waveform: click or drag to scrub */}
          <div
            onPointerDown={beginSeek}
            onPointerMove={onMove}
            onPointerUp={onUp}
            className="absolute inset-x-0 cursor-pointer"
            style={{ top: RULER_H, height: THUMBS_H + WAVE_H }}
          >
            <div className="absolute inset-x-0 top-0 overflow-hidden bg-black/40" style={{ height: THUMBS_H }}>
              {thumbs &&
                thumbsSrc &&
                tiles.map((tile) => (
                  <div
                    key={tile.x}
                    className="absolute top-0 border-r border-black/40"
                    style={{
                      left: tile.x,
                      width: tile.w,
                      height: THUMBS_H,
                      backgroundImage: `url("${thumbsSrc}")`,
                      backgroundSize: `${thumbs.cols * thumbs.tile_w * tileScale}px auto`,
                      backgroundPosition: `${-(tile.index % thumbs.cols) * thumbs.tile_w * tileScale}px ${-Math.floor(tile.index / thumbs.cols) * THUMBS_H}px`
                    }}
                  />
                ))}
            </div>
            <canvas
              ref={canvasRef}
              className="absolute"
              style={{ left: scrollLeft, top: THUMBS_H, width: viewW, height: WAVE_H }}
            />
          </div>

          {/* Clip lane */}
          <div
            onPointerDown={(e) => {
              if (e.target === e.currentTarget) props.onSelect(null)
            }}
            className="absolute inset-x-0 border-t border-line bg-black/20"
            style={{ top: RULER_H + THUMBS_H + WAVE_H, height: CLIPS_H }}
          >
            {clips.map((clip) => {
              const selected = clip.id === selectedId
              const shown = selected && range ? range : { start: clip.start_ms, end: clip.end_ms }
              return (
                <div
                  key={clip.id}
                  onPointerDown={selected ? beginMove : (e) => (e.stopPropagation(), props.onSelect(clip.id))}
                  onPointerMove={selected ? onMove : undefined}
                  onPointerUp={selected ? onUp : undefined}
                  title={selected ? 'Drag to move the clip' : clip.title}
                  className={`absolute top-1 bottom-1 truncate rounded px-1.5 text-[11px] leading-[18px] ${
                    selected ? 'z-10 cursor-grab bg-amber-400 font-medium text-black' : 'cursor-pointer bg-accent/70 text-white hover:bg-accent'
                  }`}
                  style={{ left: xFor(shown.start), width: Math.max(4, xFor(shown.end) - xFor(shown.start)) }}
                >
                  {clip.title}
                </div>
              )
            })}
            {selectedId === null && range && (
              <div
                className="pointer-events-none absolute top-1 bottom-1 rounded border border-dashed border-amber-400 bg-amber-400/15 px-1.5 text-[11px] leading-[16px] text-amber-300"
                style={{ left: xFor(range.start), width: Math.max(4, xFor(range.end) - xFor(range.start)) }}
              >
                New clip
              </div>
            )}
          </div>

          {/* Range highlight + handles */}
          {range && (
            <>
              <div
                className="pointer-events-none absolute bg-amber-400/10"
                style={{ left: xFor(range.start), width: xFor(range.end) - xFor(range.start), top: RULER_H, height: THUMBS_H + WAVE_H }}
              />
              {handle('start', range.start)}
              {handle('end', range.end)}
            </>
          )}

          {/* Parts removed by Tighten */}
          {(props.cuts ?? []).map((c) => (
            <div
              key={c.start}
              title={c.reason === 'filler' ? 'Filler word removed' : 'Pause shortened'}
              className="pointer-events-none absolute z-10 border-x border-red-400/60"
              style={{
                left: xFor(c.start),
                width: Math.max(2, xFor(c.end) - xFor(c.start)),
                top: RULER_H + THUMBS_H,
                height: WAVE_H + CLIPS_H,
                background: 'repeating-linear-gradient(135deg, rgba(248,113,113,0.45) 0 4px, rgba(0,0,0,0.35) 4px 8px)'
              }}
            />
          ))}

          {/* Playhead */}
          <div className="pointer-events-none absolute top-0 z-30 w-px bg-white" style={{ left: xFor(currentMs), height: TOTAL_H }}>
            <div className="absolute -top-px -left-[5px] size-0 border-x-[5px] border-t-[7px] border-x-transparent border-t-white" />
          </div>
        </div>
      </div>
    </div>
  )
}
