import type { AnalysisMode, AnalyzeParams, SpeechModel } from './api'

/** Remembered Find clips settings, shared by the Find clips dialog and "find clips when ready". */
export const PREFS_KEY = 'clipping.autoClipPrefs'

export interface Prefs {
  mode: AnalysisMode
  auto: boolean
  count: number
  min: number
  max: number
  model: SpeechModel
  language: string
}

export const DEFAULT_PREFS: Prefs = { mode: 'talking', auto: true, count: 5, min: 30, max: 60, model: 'base', language: '' }

export function loadPrefs(): Prefs {
  try {
    const raw = localStorage.getItem(PREFS_KEY)
    return raw ? { ...DEFAULT_PREFS, ...JSON.parse(raw) } : DEFAULT_PREFS
  } catch {
    return DEFAULT_PREFS
  }
}

/** Settings for a whole-video run with the remembered preferences (no keywords, no range). */
export function paramsFromPrefs(prefs: Prefs): AnalyzeParams {
  return {
    mode: prefs.mode,
    clip_count: prefs.auto ? null : prefs.count,
    min_seconds: prefs.min,
    max_seconds: prefs.max,
    keywords: [],
    range_start_ms: null,
    range_end_ms: null,
    model: prefs.model,
    language: prefs.language || null
  }
}

const MODE_NAMES: Record<AnalysisMode, string> = { talking: 'Talking', action: 'Action', even: 'Even split' }

/** One-line summary, e.g. "Action · 30–60 s · as many as fit". */
export function describePrefs(prefs: Prefs): string {
  const count = prefs.mode === 'even' || !prefs.auto ? `${prefs.count} clips` : 'as many as fit'
  return `${MODE_NAMES[prefs.mode] ?? prefs.mode} · ${prefs.min}–${prefs.max} s · ${count}`
}
