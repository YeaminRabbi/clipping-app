import { useEffect, useState, type ReactNode } from 'react'
import type { AppInfo } from '../../../shared/types'
import { useApp } from '../store'

const VENDOR_NAMES: Record<string, string> = { nvidia: 'NVIDIA', intel: 'Intel', amd: 'AMD', apple: 'Apple' }

function Row({ label, ok, children }: { label: string; ok: boolean | null; children: ReactNode }) {
  const icon = ok === null ? '…' : ok ? '✓' : '✕'
  const color = ok === null ? 'text-muted' : ok ? 'text-emerald-400' : 'text-red-400'
  return (
    <div className="flex gap-3 border-t border-line py-3 first:border-t-0">
      <span className={`w-4 text-center font-semibold ${color}`}>{icon}</span>
      <div className="min-w-0 flex-1">
        <div className="text-sm font-medium">{label}</div>
        <div className="mt-0.5 text-xs break-words text-muted">{children}</div>
      </div>
    </div>
  )
}

export function SystemCheck() {
  const engine = useApp((s) => s.engine)
  const health = useApp((s) => s.health)
  const restartEngine = useApp((s) => s.restartEngine)
  const [appInfo, setAppInfo] = useState<AppInfo | null>(null)
  useEffect(() => {
    void window.clipping.app.info().then(setAppInfo)
  }, [])

  const ready = engine.state === 'ready'
  const ff = health?.ffmpeg
  const encoders = ff ? Object.keys(ff.hw_encoders) : []

  return (
    <section className="h-fit rounded-xl border border-line bg-panel p-5">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-sm font-semibold">System check</h2>
        <button
          onClick={() => void restartEngine()}
          disabled={engine.state === 'starting'}
          className="rounded-md border border-line px-2.5 py-1 text-xs text-muted hover:bg-panel-2 disabled:opacity-50"
        >
          Restart engine
        </button>
      </div>

      <Row label="Processing engine" ok={engine.state === 'starting' ? null : ready}>
        {ready && health ? `v${health.version} · ${engine.url}` : engine.state === 'starting' ? 'Starting…' : engine.error}
      </Row>
      <Row label="Database" ok={health ? health.db.schema_version > 0 : ready ? null : false}>
        {health ? `Schema v${health.db.schema_version} · ${health.db.path}` : '—'}
      </Row>
      <Row label="FFmpeg" ok={ff ? !!ff.ffmpeg.path : ready ? null : false}>
        {ff?.ffmpeg.path ? `${ff.ffmpeg.version} (${ff.ffmpeg.source})` : ff ? 'Not found — run "npm run bundle:ffmpeg"' : '—'}
      </Row>
      <Row label="FFprobe" ok={ff ? !!ff.ffprobe.path : ready ? null : false}>
        {ff?.ffprobe.path ? `${ff.ffprobe.version} (${ff.ffprobe.source})` : ff ? 'Not found' : '—'}
      </Row>
      <Row label="Hardware encoding" ok={ff ? encoders.length > 0 : ready ? null : false}>
        {ff
          ? encoders.length
            ? encoders.map((v) => `${VENDOR_NAMES[v] ?? v} (${ff.hw_encoders[v].join(', ')})`).join(' · ')
            : 'None in this FFmpeg build — exports will use the CPU'
          : '—'}
      </Row>

      <div className="mt-3 flex items-center justify-between border-t border-line pt-3 text-xs text-muted">
        <span>{appInfo ? `Clipping App ${appInfo.version}` : ''}</span>
        <button onClick={() => void window.clipping.app.openLogs()} className="rounded-md px-2 py-1 hover:bg-panel-2 hover:text-white">
          Open logs folder
        </button>
      </div>

      {engine.state === 'error' && engine.logs.length > 0 && (
        <pre className="mt-3 max-h-48 overflow-auto rounded-md bg-black/40 p-3 text-[11px] text-muted">
          {engine.logs.slice(-20).join('\n')}
        </pre>
      )}
    </section>
  )
}
