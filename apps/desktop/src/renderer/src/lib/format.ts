export function formatDuration(ms: number | null): string {
  if (ms === null) return '—'
  const total = Math.round(ms / 1000)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  const pad = (n: number): string => n.toString().padStart(2, '0')
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`
}

export function formatBytes(bytes: number | null): string {
  if (bytes === null) return '—'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let value = bytes
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit++
  }
  return `${value.toFixed(value >= 100 || unit === 0 ? 0 : 1)} ${units[unit]}`
}

/** "1080p" for 1920x1080 or 1080x1920; the shorter side is what people call the resolution. */
export function formatResolution(width: number | null, height: number | null): string {
  if (!width || !height) return '—'
  return `${Math.min(width, height)}p`
}

export function formatFps(fps: number | null): string {
  if (!fps) return '—'
  return `${Number.isInteger(fps) ? fps : fps.toFixed(2)} fps`
}
