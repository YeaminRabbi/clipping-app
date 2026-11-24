import { useEffect, type RefObject } from 'react'
import type { Clip, EngineClient } from '../../lib/api'

export function useAudioPreview(videoRef: RefObject<HTMLVideoElement | null>, clip: Clip | null, client: EngineClient | null,
  segmentsRef: RefObject<[number, number][]>, indexRef: RefObject<number>, muted: boolean) {
  useEffect(() => {
    const video = videoRef.current
    if (!video || !clip || !client || !clip.audio?.length) return
    const nodes = clip.audio.map((layer) => ({ layer, audio: new Audio(client.mediaUrl(`/media/audio/${layer.asset_id}`)) }))
    let handle = 0
    const tick = () => {
      const segments = segmentsRef.current
      const index = indexRef.current
      const current = segments[index] ?? [clip.start_ms, clip.end_ms]
      const ms = segments.slice(0, index).reduce((n, [a, b]) => n + b - a, 0) + video.currentTime * 1000 - current[0]
      let original = 1
      for (const { layer, audio } of nodes) {
        const active = ms >= layer.start_ms && ms < layer.end_ms
        if (active) original *= layer.original_volume
        audio.volume = Math.min(1, layer.volume)
        audio.muted = muted
        audio.playbackRate = video.playbackRate
        if (active && !video.paused && !video.seeking) {
          const target = (layer.offset_ms + ms - layer.start_ms) / 1000
          if (Math.abs(audio.currentTime - target) > 0.12) audio.currentTime = target
          if (audio.paused) void audio.play().catch(() => {})
        } else audio.pause()
      }
      video.volume = original
      handle = requestAnimationFrame(tick)
    }
    handle = requestAnimationFrame(tick)
    return () => {
      cancelAnimationFrame(handle)
      nodes.forEach(({ audio }) => { audio.pause(); audio.removeAttribute('src'); audio.load() })
      video.volume = 1
    }
  }, [videoRef, clip?.id, JSON.stringify(clip?.audio), client, segmentsRef, indexRef, muted])
}
