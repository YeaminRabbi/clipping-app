import { Volume2, VolumeX } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { EngineClient } from '../../lib/api'

type PlayerState = 'connecting' | 'playing' | 'unsupported' | 'error'

/** Codec string for MediaSource, read from the preview's init segment (H.264 + AAC only). */
function codecsFromInit(init: Uint8Array): string[] | null {
  const find = (tag: string): number => {
    const a = tag.charCodeAt(0)
    for (let i = 0; i + 3 < init.length; i++) {
      if (init[i] === a && init[i + 1] === tag.charCodeAt(1) && init[i + 2] === tag.charCodeAt(2) && init[i + 3] === tag.charCodeAt(3)) {
        return i
      }
    }
    return -1
  }
  const avcC = find('avcC')
  if (avcC < 0 || avcC + 8 > init.length) return null // HEVC or AV1: not shown in the preview
  const hex = (n: number) => n.toString(16).padStart(2, '0')
  // avcC body: configurationVersion, AVCProfileIndication, profile_compatibility, AVCLevelIndication
  const codecs = [`avc1.${hex(init[avcC + 5])}${hex(init[avcC + 6])}${hex(init[avcC + 7])}`]
  if (find('mp4a') >= 0) codecs.push('mp4a.40.2')
  return codecs
}

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

/**
 * Plays the recorder's rolling preview (fragmented MP4 pieces on this machine) with MediaSource,
 * staying a few seconds behind live. Recording doesn't depend on it: if the preview can't play,
 * the recording carries on.
 */
export function LivePlayer({ client, previewUrl }: { client: EngineClient; previewUrl: string | null }) {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const [state, setState] = useState<PlayerState>('connecting')
  const [muted, setMuted] = useState(false)
  const [volume, setVolume] = useState(0.8)

  useEffect(() => {
    const video = videoRef.current
    if (!video || !previewUrl) return
    let stopped = false
    const dir = previewUrl.slice(0, previewUrl.lastIndexOf('/') + 1)
    const media = new MediaSource()
    const objectUrl = URL.createObjectURL(media)
    video.src = objectUrl
    setState('connecting')

    const fetchBytes = async (name: string): Promise<ArrayBuffer | null> => {
      const res = await fetch(client.mediaUrl(dir + name), { cache: 'no-store' })
      return res.ok ? res.arrayBuffer() : null
    }

    const append = (buffer: SourceBuffer, data: ArrayBuffer) =>
      new Promise<void>((resolve, reject) => {
        const done = () => {
          buffer.removeEventListener('updateend', done)
          buffer.removeEventListener('error', fail)
          resolve()
        }
        const fail = () => {
          buffer.removeEventListener('updateend', done)
          buffer.removeEventListener('error', fail)
          reject(new Error('append failed'))
        }
        buffer.addEventListener('updateend', done)
        buffer.addEventListener('error', fail)
        buffer.appendBuffer(data)
      })

    const run = async () => {
      // The first pieces appear a couple of seconds after recording starts.
      let init: ArrayBuffer | null = null
      while (!stopped && !(init = await fetchBytes('init.mp4').catch(() => null))) await sleep(1000)
      if (stopped || !init) return
      const codecs = codecsFromInit(new Uint8Array(init))
      const mime = codecs && `video/mp4; codecs="${codecs.join(', ')}"`
      if (!mime || !MediaSource.isTypeSupported(mime)) {
        setState('unsupported')
        return
      }
      const buffer = media.addSourceBuffer(mime)
      await append(buffer, init)

      const done = new Set<string>()
      let first = true
      while (!stopped) {
        try {
          const res = await fetch(client.mediaUrl(dir + 'index.m3u8'), { cache: 'no-store' })
          if (res.ok) {
            const names = (await res.text())
              .split('\n')
              .map((l) => l.trim())
              .filter((l) => l && !l.startsWith('#'))
            // Join near the live edge rather than from the oldest piece still listed.
            const todo = (first ? names.slice(-3) : names).filter((n) => !done.has(n))
            first = false
            for (const name of todo) {
              if (stopped) break
              done.add(name)
              const data = await fetchBytes(name)
              if (data && media.readyState === 'open') await append(buffer, data)
            }
            if (done.size > 200) for (const n of [...done].slice(0, 100)) done.delete(n)
          }

          const { buffered } = video
          if (buffered.length) {
            const end = buffered.end(buffered.length - 1)
            // Fell behind (e.g. the window was hidden): jump back near live.
            if (end - video.currentTime > 10) video.currentTime = Math.max(buffered.start(buffered.length - 1), end - 3)
            if (video.paused) {
              await video.play().catch(() => undefined)
            }
            // Keep about half a minute in memory.
            const start = buffered.start(0)
            if (video.currentTime - start > 45 && !buffer.updating) {
              await new Promise<void>((resolve) => {
                buffer.addEventListener('updateend', () => resolve(), { once: true })
                buffer.remove(start, video.currentTime - 20)
              })
            }
            if (!video.paused) setState('playing')
          }
        } catch {
          // A missed piece only skips a moment of preview; keep going.
        }
        await sleep(1000)
      }
    }

    const onOpen = () => {
      run().catch(() => {
        if (!stopped) setState('error')
      })
    }
    media.addEventListener('sourceopen', onOpen, { once: true })

    return () => {
      stopped = true
      media.removeEventListener('sourceopen', onOpen)
      video.removeAttribute('src')
      video.load()
      URL.revokeObjectURL(objectUrl)
    }
  }, [client, previewUrl])

  useEffect(() => {
    const video = videoRef.current
    if (!video) return
    video.muted = muted
    video.volume = volume
  }, [muted, volume])

  const message =
    !previewUrl
      ? 'Waiting for the stream'
      : state === 'connecting'
        ? 'Connecting to the stream'
        : state === 'unsupported'
          ? "This stream's video format can't be previewed here. It's still being recorded."
          : state === 'error'
            ? "The preview stopped. The recording carries on."
            : null

  return (
    <div className="video-surface relative aspect-video w-full overflow-hidden rounded-2xl border border-line">
      <video ref={videoRef} className="size-full object-contain" playsInline />
      {message && (
        <div className="absolute inset-0 grid place-items-center px-6 text-center text-sm text-muted">{message}</div>
      )}
      <div className="absolute right-3 bottom-3 flex items-center gap-2 rounded-full bg-[rgba(6,10,20,0.75)] py-1 pr-3 pl-1">
        <button
          onClick={() => setMuted(!muted)}
          aria-label={muted ? 'Unmute' : 'Mute'}
          title="Only changes what you hear. The recording keeps its sound."
          className="not-pill grid size-8 place-items-center rounded-full text-ink hover:bg-white/10"
        >
          {muted ? <VolumeX size={16} aria-hidden /> : <Volume2 size={16} aria-hidden />}
        </button>
        <input
          type="range"
          min={0}
          max={1}
          step={0.05}
          value={muted ? 0 : volume}
          onChange={(e) => {
            setVolume(Number(e.target.value))
            setMuted(false)
          }}
          aria-label="Preview volume"
          className="w-24"
        />
      </div>
    </div>
  )
}
