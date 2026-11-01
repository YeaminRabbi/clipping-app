import type { Crop, Keyframe } from './api'

/** Crop at source time t (ms) along a smart-framing path; mirrors engine/app/reframe/track.py crop_at. */
export function cropAt(keyframes: Keyframe[], t: number): Crop {
  const first = keyframes[0]
  if (t <= first.t) return first
  for (let i = 1; i < keyframes.length; i++) {
    const a = keyframes[i - 1]
    const b = keyframes[i]
    if (t <= b.t) {
      const f = (t - a.t) / Math.max(b.t - a.t, 1)
      return { x: a.x + (b.x - a.x) * f, y: a.y + (b.y - a.y) * f, w: a.w + (b.w - a.w) * f, h: a.h + (b.h - a.h) * f }
    }
  }
  return keyframes[keyframes.length - 1]
}

export interface AspectPreset {
  key: string
  label: string
  short: string
  ratio: number // width / height
}

// Mirrors engine/app/aspects.py.
export const ASPECTS: AspectPreset[] = [
  { key: '9:16', label: 'Phone (Reels / TikTok / Shorts)', short: 'Phone', ratio: 9 / 16 },
  { key: '4:5', label: 'Instagram portrait', short: 'IG portrait', ratio: 4 / 5 },
  { key: '1:1', label: 'Instagram square', short: 'Square', ratio: 1 },
  { key: '16:9', label: 'Desktop / YouTube', short: 'Desktop', ratio: 16 / 9 },
  { key: '4:3', label: 'Tablet', short: 'Tablet', ratio: 4 / 3 }
]

export const aspectRatio = (key: string): number => ASPECTS.find((a) => a.key === key)?.ratio ?? 9 / 16

/** Largest centered crop of the target aspect. */
export function defaultCrop(aspect: string, srcW: number, srcH: number): Crop {
  const target = aspectRatio(aspect)
  const src = srcW / srcH
  const [w, h] = target < src ? [target / src, 1] : [1, src / target]
  return { x: (1 - w) / 2, y: (1 - h) / 2, w, h }
}

/** Keep a crop inside the frame (moving it first, shrinking only if it's too big). */
export function clampCrop(crop: Crop): Crop {
  const w = Math.min(crop.w, 1)
  const h = Math.min(crop.h, 1)
  return { w, h, x: Math.min(Math.max(crop.x, 0), 1 - w), y: Math.min(Math.max(crop.y, 0), 1 - h) }
}
