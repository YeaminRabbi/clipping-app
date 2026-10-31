/**
 * Frame math. Times are stored in milliseconds, but every edit snaps to a frame boundary of the
 * source so what you see in the editor is exactly what gets exported.
 */

export const msToFrame = (ms: number, fps: number): number => Math.round((ms * fps) / 1000)

export const frameToMs = (frame: number, fps: number): number => Math.round((frame * 1000) / fps)

export const snapMs = (ms: number, fps: number): number => frameToMs(msToFrame(ms, fps), fps)

/** 1:02:03.15 style timecode (the last part is the frame within the second). */
export function timecode(ms: number, fps: number): string {
  const frame = msToFrame(ms, fps)
  const fpsInt = Math.round(fps)
  const totalSeconds = Math.floor(frame / fps)
  const ff = Math.min(fpsInt - 1, Math.round(frame - totalSeconds * fps))
  const h = Math.floor(totalSeconds / 3600)
  const m = Math.floor((totalSeconds % 3600) / 60)
  const s = totalSeconds % 60
  const pad = (n: number): string => n.toString().padStart(2, '0')
  return `${h > 0 ? `${h}:${pad(m)}` : m}:${pad(s)}.${pad(ff)}`
}

/** Short human duration: 12.4s, 1:05 */
export function shortDuration(ms: number): string {
  const s = ms / 1000
  if (s < 60) return `${s.toFixed(1)}s`
  const m = Math.floor(s / 60)
  return `${m}:${Math.floor(s % 60)
    .toString()
    .padStart(2, '0')}`
}
