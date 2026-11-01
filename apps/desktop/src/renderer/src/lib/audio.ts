import type { ClipAudio } from './api'

export function monitorVolumeFromStorage(stored: string | null): number {
  if (stored === null || stored.trim() === '') return 100
  const value = Number(stored)
  return Number.isFinite(value) ? Math.min(100, Math.max(0, value)) : 100
}

/** Linear gain heard by the editor. Monitoring controls never change the persisted clip value. */
export function previewGain(monitorVolume: number, monitorMuted: boolean, clip: ClipAudio): number {
  if (monitorMuted || clip.muted) return 0
  return (Math.min(100, Math.max(0, monitorVolume)) / 100) * (Math.min(200, Math.max(0, clip.level)) / 100)
}

/** Linear gain intended for export; deliberately has no monitoring inputs. */
export function clipExportGain(clip: ClipAudio): number {
  return clip.muted ? 0 : Math.min(200, Math.max(0, clip.level)) / 100
}

export interface PreviewAudioGraph {
  context: AudioContext
  source: MediaElementAudioSourceNode
  gain: GainNode
  limiter: DynamicsCompressorNode
  releaseTimer: ReturnType<typeof setTimeout> | null
}

const graphs = new WeakMap<HTMLVideoElement, PreviewAudioGraph>()

/**
 * Attach one reusable Web Audio graph to a video element. React Strict Mode immediately cleans up
 * and reruns effects in development, but a media element may only ever have one MediaElementSource.
 */
export function acquirePreviewAudioGraph(
  video: HTMLVideoElement,
  createContext: () => AudioContext = () => new AudioContext()
): PreviewAudioGraph | null {
  const existing = graphs.get(video)
  if (existing) {
    if (existing.releaseTimer !== null) clearTimeout(existing.releaseTimer)
    existing.releaseTimer = null
    return existing
  }

  try {
    const context = createContext()
    const source = context.createMediaElementSource(video)
    const gain = context.createGain()
    const limiter = context.createDynamicsCompressor()
    limiter.threshold.value = -1
    limiter.knee.value = 0
    limiter.ratio.value = 20
    limiter.attack.value = 0.003
    limiter.release.value = 0.1
    source.connect(gain).connect(limiter).connect(context.destination)
    const graph = { context, source, gain, limiter, releaseTimer: null }
    graphs.set(video, graph)
    return graph
  } catch {
    return null
  }
}

/** Defer disposal so a Strict Mode effect rerun can reacquire the element's one permitted graph. */
export function releasePreviewAudioGraph(video: HTMLVideoElement, graph: PreviewAudioGraph): void {
  if (graph.releaseTimer !== null) clearTimeout(graph.releaseTimer)
  graph.releaseTimer = setTimeout(() => {
    if (graphs.get(video) !== graph) return
    graph.source.disconnect()
    graph.gain.disconnect()
    graph.limiter.disconnect()
    graphs.delete(video)
    void graph.context.close()
  }, 0)
}

export function applyPreviewAudioGain(
  video: Pick<HTMLVideoElement, 'volume' | 'muted'>,
  graph: PreviewAudioGraph | null,
  effectiveGain: number
): void {
  const gain = Math.max(0, effectiveGain)
  if (graph) {
    // The element stays at unity; applying gain both here and in Web Audio would square the level.
    video.volume = 1
    video.muted = false
    graph.gain.gain.setTargetAtTime(gain, graph.context.currentTime, 0.01)
  } else {
    // HTMLMediaElement.volume is strictly 0.0-1.0; older players cannot preview boosts.
    video.volume = Math.min(1, gain)
    video.muted = gain === 0
  }
}

export async function resumePreviewAudio(graph: PreviewAudioGraph | null): Promise<void> {
  if (graph && graph.context.state === 'suspended') await graph.context.resume()
}
