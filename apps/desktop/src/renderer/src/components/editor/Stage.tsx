import { useEffect, useRef, useState, type CSSProperties, type RefObject } from 'react'
import type { ClipCaptions, Crop, FitStyle, FramingMode } from '../../lib/api'
import { CaptionOverlay } from './CaptionOverlay'
import { CropOverlay } from './CropOverlay'

interface Props {
  videoRef: RefObject<HTMLVideoElement | null>
  src: string
  poster: string | undefined
  srcAspect: number
  targetRatio: number
  mode: FramingMode
  crop: Crop
  fit: FitStyle
  /** Captions to draw over the output preview (null = none). */
  captions: ClipCaptions | null
  timeMs: number
  view: 'edit' | 'preview'
  editable: boolean
  onCropChange(crop: Crop, final: boolean): void
  onTogglePlay(): void
}

function contain(boxW: number, boxH: number, aspect: number): { w: number; h: number } {
  return boxW / boxH > aspect ? { w: boxH * aspect, h: boxH } : { w: boxW, h: boxW / aspect }
}

/**
 * The video, either as the full source frame with the crop box on top ("edit"), or showing only what
 * the exported clip will contain ("preview"). One <video> element is reused for both so switching
 * views never reloads or loses the playback position.
 */
export function Stage(props: Props) {
  const { videoRef, src, poster, srcAspect, targetRatio, mode, crop, fit, view, editable } = props
  const stageRef = useRef<HTMLDivElement>(null)
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const [size, setSize] = useState({ w: 0, h: 0 })

  useEffect(() => {
    const el = stageRef.current
    if (!el) return
    const observer = new ResizeObserver(([entry]) =>
      setSize({ w: entry.contentRect.width, h: entry.contentRect.height })
    )
    observer.observe(el)
    return () => observer.disconnect()
  }, [])

  const frame = contain(size.w, size.h, view === 'edit' ? srcAspect : targetRatio)
  const blurBackground = view === 'preview' && mode === 'fit' && fit.background === 'blur'

  // Live blurred background for the fit preview: redraw the current video frame, zoomed to cover.
  useEffect(() => {
    const video = videoRef.current
    const canvas = canvasRef.current
    if (!blurBackground || !video || !canvas || frame.w === 0) return
    const dpr = window.devicePixelRatio || 1
    canvas.width = Math.round(frame.w * dpr)
    canvas.height = Math.round(frame.h * dpr)
    const ctx = canvas.getContext('2d')
    if (!ctx) return
    const draw = () => {
      const cover = frame.w / frame.h > srcAspect ? { w: frame.w, h: frame.w / srcAspect } : { w: frame.h * srcAspect, h: frame.h }
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
      ctx.filter = `blur(${Math.max(4, frame.w * 0.04)}px) brightness(${1 - fit.dim})`
      ctx.drawImage(video, (frame.w - cover.w) / 2 - 20, (frame.h - cover.h) / 2 - 20, cover.w + 40, cover.h + 40)
    }
    let handle = 0
    const loop = () => {
      draw()
      handle = video.requestVideoFrameCallback(loop)
    }
    draw()
    handle = video.requestVideoFrameCallback(loop)
    const onSeeked = () => draw()
    video.addEventListener('seeked', onSeeked)
    return () => {
      video.cancelVideoFrameCallback(handle)
      video.removeEventListener('seeked', onSeeked)
    }
  }, [blurBackground, frame.w, frame.h, srcAspect, fit.dim, videoRef])

  // The visible picture box inside the frame, and the video's position inside that box.
  let box: CSSProperties = { left: 0, top: 0, width: frame.w, height: frame.h }
  let videoStyle: CSSProperties = { left: 0, top: 0, width: '100%', height: '100%' }
  if (view === 'preview' && mode !== 'fit') {
    const width = frame.w / crop.w
    const height = width / srcAspect
    videoStyle = { left: -crop.x * width, top: -crop.y * height, width, height }
  } else if (view === 'preview' && mode === 'fit') {
    // Mirrors the export: fit inside the frame scaled by zoom, edges trimmed, placed center or top.
    const inner = contain(frame.w * fit.zoom, frame.h * fit.zoom, srcAspect)
    const visW = Math.min(inner.w, frame.w)
    const visH = Math.min(inner.h, frame.h)
    const top = fit.position === 'top' ? (frame.h - visH) * 0.15 : (frame.h - visH) / 2
    box = { left: (frame.w - visW) / 2, top, width: visW, height: visH }
    videoStyle = { left: -(inner.w - visW) / 2, top: -(inner.h - visH) / 2, width: inner.w, height: inner.h }
  }

  const solid = view === 'preview' && mode === 'fit' && fit.background !== 'blur'

  return (
    <div ref={stageRef} className="relative grid min-h-0 flex-1 place-items-center overflow-hidden bg-black">
      <div
        className="relative overflow-hidden"
        style={{ width: frame.w, height: frame.h, background: solid ? fit.background : undefined }}
      >
        {blurBackground && <canvas ref={canvasRef} className="absolute inset-0 size-full" />}
        <div className="absolute overflow-hidden" style={box}>
          <video
            ref={videoRef}
            src={src}
            poster={poster}
            preload="auto"
            playsInline
            onClick={props.onTogglePlay}
            className="absolute max-w-none object-fill"
            style={videoStyle}
          />
        </div>
        {view === 'preview' && props.captions && frame.h > 0 && (
          <CaptionOverlay cues={props.captions.cues} style={props.captions.style} timeMs={props.timeMs} frameH={frame.h} />
        )}
        {view === 'edit' && mode !== 'fit' && frame.w > 0 && (
          <CropOverlay
            crop={crop}
            frameW={frame.w}
            frameH={frame.h}
            targetRatio={targetRatio}
            srcAspect={srcAspect}
            editable={editable}
            onChange={props.onCropChange}
          />
        )}
        {view === 'edit' && mode !== 'manual' && (
          <div className="pointer-events-none absolute inset-x-0 bottom-3 text-center">
            <span className="rounded bg-black/70 px-2 py-1 text-xs text-white/90">
              {mode === 'fit'
                ? 'Fit: the whole frame is kept. Switch to “Preview output” to see the background.'
                : 'Smart: the crop follows faces. Drag it to fix the position yourself.'}
            </span>
          </div>
        )}
      </div>
    </div>
  )
}
