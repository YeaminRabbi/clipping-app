import type { ExportJob } from '../lib/api'
import { useApp } from '../store'

const STATUS_LABEL: Record<ExportJob['status'], string> = {
  queued: 'Waiting…',
  rendering: 'Rendering',
  done: 'Done',
  failed: 'Failed',
  cancelled: 'Cancelled'
}

function encoderLabel(encoder: string | null): string | null {
  if (!encoder) return null
  if (encoder.startsWith('lib')) return 'CPU'
  if (encoder.includes('nvenc')) return 'NVIDIA GPU'
  if (encoder.includes('qsv')) return 'Intel GPU'
  if (encoder.includes('amf')) return 'AMD GPU'
  if (encoder.includes('videotoolbox')) return 'Apple GPU'
  return encoder
}

export function ExportsPanel() {
  const jobs = useApp((s) => s.exports)
  const batches = useApp((s) => s.exportBatches)
  const { cancelExport, retryExport, clearFinishedExports } = useApp.getState()
  if (jobs.length === 0) return null
  const zips = batches.filter((b) => b.zip_path || b.error).slice(0, 3)

  const active = jobs.filter((j) => j.status === 'queued' || j.status === 'rendering').length
  const done = jobs.filter((j) => j.status === 'done')
  const folder = done[0]?.output_path?.replace(/[\\/][^\\/]+$/, '')

  return (
    <section className="rounded-xl border border-line bg-panel p-5">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">
          Exports{' '}
          <span className="font-normal text-muted">
            ({active > 0 ? `${active} in progress, ` : ''}
            {done.length} done)
          </span>
        </h2>
        <div className="flex gap-1">
          {folder && (
            <button
              onClick={() => void window.clipping.files.openPath(folder)}
              className="rounded-md px-2.5 py-1 text-xs text-muted hover:bg-panel-2 hover:text-white"
            >
              Open folder
            </button>
          )}
          {jobs.length > active && (
            <button
              onClick={() => void clearFinishedExports()}
              className="rounded-md px-2.5 py-1 text-xs text-muted hover:bg-panel-2 hover:text-white"
            >
              Clear finished
            </button>
          )}
        </div>
      </div>

      {zips.map((b) => (
        <div
          key={b.id}
          className={`mt-3 flex items-center justify-between gap-3 rounded-md border px-3 py-2 text-xs ${b.error ? 'border-red-900/60 text-red-300' : 'border-emerald-900/60 text-emerald-300'}`}
        >
          <span className="min-w-0 truncate">{b.error ?? `ZIP ready: ${b.zip_path?.split(/[\\/]/).pop()}`}</span>
          {b.zip_path && (
            <button onClick={() => void window.clipping.files.showInFolder(b.zip_path!)} className="shrink-0 text-white/80 hover:text-white">
              Show
            </button>
          )}
        </div>
      ))}

      <ul className="mt-3 flex flex-col gap-1.5">
        {jobs.map((job) => {
          const running = job.status === 'rendering' || job.status === 'queued'
          const percent = Math.round(job.progress * 100)
          return (
            <li key={job.id} className="rounded-md border border-line bg-panel-2 px-3 py-2">
              <div className="flex items-center gap-3">
                <span className="w-10 shrink-0 rounded bg-black/30 px-1.5 py-0.5 text-center text-[10px] text-muted">{job.aspect}</span>
                <span className="min-w-0 flex-1 truncate text-sm" title={job.output_path ?? job.output_name}>
                  {job.output_path?.split(/[\\/]/).pop() ?? `${job.output_name}.mp4`}
                </span>
                <span className={`text-xs ${job.status === 'failed' ? 'text-red-300' : job.status === 'done' ? 'text-emerald-400' : 'text-muted'}`}>
                  {STATUS_LABEL[job.status]}
                  {job.status === 'rendering' && ` ${percent}%`}
                  {encoderLabel(job.encoder) && job.status !== 'queued' && ` · ${encoderLabel(job.encoder)}`}
                  {job.burn_captions && ' · captions'}
                  {job.srt_path && ' · .srt'}
                </span>
                {running && (
                  <button onClick={() => void cancelExport(job.id)} className="rounded px-2 py-0.5 text-xs text-muted hover:bg-panel hover:text-white">
                    Cancel
                  </button>
                )}
                {(job.status === 'failed' || job.status === 'cancelled') && (
                  <button onClick={() => void retryExport(job.id)} className="rounded px-2 py-0.5 text-xs text-muted hover:bg-panel hover:text-white">
                    Retry
                  </button>
                )}
                {job.status === 'done' && job.output_path && (
                  <>
                    <button
                      onClick={() => void window.clipping.files.openPath(job.output_path!)}
                      className="rounded px-2 py-0.5 text-xs text-muted hover:bg-panel hover:text-white"
                    >
                      Play
                    </button>
                    <button
                      onClick={() => void window.clipping.files.showInFolder(job.output_path!)}
                      className="rounded px-2 py-0.5 text-xs text-muted hover:bg-panel hover:text-white"
                    >
                      Show
                    </button>
                  </>
                )}
              </div>
              {running && (
                <div className="mt-2 h-1 overflow-hidden rounded-full bg-black/40">
                  <div
                    className={`h-full rounded-full bg-accent transition-[width] duration-300 ${job.status === 'queued' ? 'animate-pulse' : ''}`}
                    style={{ width: `${Math.max(percent, 2)}%` }}
                  />
                </div>
              )}
              {job.status === 'failed' && job.error && <div className="mt-1 text-xs break-words text-red-300">{job.error}</div>}
            </li>
          )
        })}
      </ul>
    </section>
  )
}
