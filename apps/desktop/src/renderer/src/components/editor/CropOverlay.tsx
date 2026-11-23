import { useRef, type PointerEvent as ReactPointerEvent } from 'react'
import type { Crop } from '../../lib/api'
import { clampCrop } from '../../lib/aspects'

type Corner = 'nw' | 'ne' | 'sw' | 'se'

const MIN_WIDTH = 0.05

interface Props {
  crop: Crop
  frameW: number
  frameH: number
  /** Output width / height. */
  targetRatio: number
  /** Source displayed width / height. */
  srcAspect: number
  editable: boolean
  onChange(crop: Crop, final: boolean): void
}

/** Crop box over the video: drag inside to move, drag a corner to resize at the locked aspect ratio. */
export function CropOverlay({ crop, frameW, frameH, targetRatio, srcAspect, editable, onChange }: Props) {
  const drag = useRef<{ kind: 'move' | Corner; startX: number; startY: number; start: Crop; last: Crop } | null>(null)

  // Normalized height for a normalized width at the target aspect.
  const heightFor = (w: number): number => (w * srcAspect) / targetRatio

  const begin = (kind: 'move' | Corner) => (e: ReactPointerEvent) => {
    if (!editable) return
    e.preventDefault()
    e.stopPropagation()
    ;(e.target as HTMLElement).setPointerCapture(e.pointerId)
    drag.current = { kind, startX: e.clientX, startY: e.clientY, start: crop, last: crop }
  }

  const move = (e: ReactPointerEvent) => {
    const d = drag.current
    if (!d) return
    let next: Crop
    if (d.kind === 'move') {
      const dx = (e.clientX - d.startX) / frameW
      const dy = (e.clientY - d.startY) / frameH
      next = clampCrop({ ...d.start, x: d.start.x + dx, y: d.start.y + dy })
    } else {
      // Resize around the opposite corner, which stays put.
      const east = d.kind === 'ne' || d.kind === 'se'
      const south = d.kind === 'sw' || d.kind === 'se'
      const anchorX = east ? d.start.x : d.start.x + d.start.w
      const anchorY = south ? d.start.y : d.start.y + d.start.h
      const px = d.start.x * frameW + (east ? d.start.w * frameW : 0) + (e.clientX - d.startX)
      const py = d.start.y * frameH + (south ? d.start.h * frameH : 0) + (e.clientY - d.startY)
      const fromX = Math.abs(px / frameW - anchorX)
      const fromY = (Math.abs(py / frameH - anchorY) * targetRatio) / srcAspect
      const availW = east ? 1 - anchorX : anchorX
      const availH = south ? 1 - anchorY : anchorY
      const w = Math.max(MIN_WIDTH, Math.min(Math.max(fromX, fromY), availW, (availH * targetRatio) / srcAspect))
      const h = heightFor(w)
      next = { w, h, x: east ? anchorX : anchorX - w, y: south ? anchorY : anchorY - h }
    }
    d.last = next
    onChange(next, false)
  }

  const end = () => {
    const d = drag.current
    drag.current = null
    if (d && d.last !== d.start) onChange(d.last, true)
  }

  const corner = (c: Corner, cls: string) => (
    <div
      onPointerDown={begin(c)}
      onPointerMove={move}
      onPointerUp={end}
      className={`absolute size-3.5 rounded-sm border-2 border-white bg-accent ${cls}`}
    />
  )

  return (
    <div className="pointer-events-none absolute inset-0 overflow-hidden">
      <div
        onPointerDown={begin('move')}
        onPointerMove={move}
        onPointerUp={end}
        className={`pointer-events-auto absolute border-2 border-white/90 ${editable ? 'cursor-move' : 'border-dashed opacity-80'}`}
        style={{
          left: crop.x * frameW,
          top: crop.y * frameH,
          width: crop.w * frameW,
          height: crop.h * frameH,
          boxShadow: '0 0 0 9999px rgba(0, 0, 0, 0.6)'
        }}
      >
        {/* Rule-of-thirds guides */}
        <div className="pointer-events-none absolute inset-y-0 left-1/3 w-px bg-white/25" />
        <div className="pointer-events-none absolute inset-y-0 left-2/3 w-px bg-white/25" />
        <div className="pointer-events-none absolute inset-x-0 top-1/3 h-px bg-white/25" />
        <div className="pointer-events-none absolute inset-x-0 top-2/3 h-px bg-white/25" />
        {editable && (
          <>
            {corner('nw', '-top-2 -left-2 cursor-nwse-resize')}
            {corner('ne', '-top-2 -right-2 cursor-nesw-resize')}
            {corner('sw', '-bottom-2 -left-2 cursor-nesw-resize')}
            {corner('se', '-right-2 -bottom-2 cursor-nwse-resize')}
          </>
        )}
      </div>
    </div>
  )
}
