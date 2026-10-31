import { ACTIVE_STATUSES, type Source } from '../lib/api'
import { formatBytes, formatDuration, formatFps, formatResolution } from '../lib/format'
import { useApp } from '../store'
import { AnalysisStatus } from './AnalysisStatus'

const STAGE_LABELS: Record<Source['status'], string> = {
  queued: 'Waiting to start…',
  downloading: 'Downloading',
  probing: 'Reading video details…',
  processing: 'Preparing preview',
  ready: 'Ready',
  failed: 'Failed',
  cancelled: 'Cancelled'
}

function displayName(source: Source): string {
  return source.title || source.url || source.path?.split(/[\\/]/).pop() || `Source ${source.id}`
}

export function SourceCard({ source, clipCount }: { source: Source; clipCount: number }) {
  const client = useApp((s) => s.client)
  const cancelSource = useApp((s) => s.cancelSource)
  const retrySource = useApp((s) => s.retrySource)
  const deleteSource = useApp((s) => s.deleteSource)
  const openEditor = useApp((s) => s.openEditor)
  const openAutoClipDialog = useApp((s) => s.openAutoClipDialog)
  const analysing = useApp((s) => ['queued', 'running'].includes(s.analyses[source.id]?.status ?? ''))

  const active = ACTIVE_STATUSES.includes(source.status)
  const percent = Math.round(source.progress * 100)
  const showPercent = source.status === 'downloading' || source.status === 'processing'
  const name = displayName(source)

  return (
    <li className="flex gap-4 rounded-lg border border-line bg-panel-2 p-3">
      <button
        onClick={() => source.status === 'ready' && openEditor(source.id)}
        disabled={source.status !== 'ready'}
        className="group relative aspect-video w-44 shrink-0 overflow-hidden rounded-md bg-black/50 enabled:cursor-pointer"
        title={source.status === 'ready' ? 'Open in editor' : undefined}
      >
        {source.poster_url && client ? (
          // Contain rather than cover so portrait (phone) videos aren't cropped in the 16:9 box.
          <img src={client.mediaUrl(source.poster_url)} alt="" className="size-full object-contain" />
        ) : (
          <div className="grid size-full place-items-center text-xs text-muted">{active ? '…' : 'No preview'}</div>
        )}
        {source.status === 'ready' && (
          <div className="absolute inset-0 grid place-items-center bg-black/40 opacity-0 transition-opacity group-hover:opacity-100">
            <span className="grid size-10 place-items-center rounded-full bg-white/90 pl-0.5 text-black">▶</span>
          </div>
        )}
        {source.duration_ms !== null && (
          <span className="absolute right-1 bottom-1 rounded bg-black/75 px-1.5 py-0.5 text-[10px] font-medium">
            {formatDuration(source.duration_ms)}
          </span>
        )}
      </button>

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="truncate text-sm font-medium" title={name}>
              {name}
            </div>
            <div className="truncate text-xs text-muted" title={source.url ?? source.path ?? ''}>
              {source.origin === 'url' ? 'Link' : 'Local file'} · {source.url ?? source.path}
            </div>
          </div>
          <div className="flex shrink-0 gap-1">
            {source.status === 'ready' && (
              <>
                <button
                  onClick={() => openAutoClipDialog(source.id)}
                  disabled={analysing}
                  className="rounded-md border border-accent/60 px-3 py-1 text-xs font-medium hover:bg-accent/20 disabled:opacity-50"
                >
                  Find clips
                </button>
                <button
                  onClick={() => openEditor(source.id)}
                  className="rounded-md bg-accent px-3 py-1 text-xs font-medium hover:bg-accent-hover"
                >
                  {clipCount > 0 ? `Edit ${clipCount} clip${clipCount === 1 ? '' : 's'}` : 'Open editor'}
                </button>
              </>
            )}
            {active && (
              <button
                onClick={() => void cancelSource(source.id)}
                className="rounded-md px-2.5 py-1 text-xs text-muted hover:bg-panel hover:text-white"
              >
                Cancel
              </button>
            )}
            {(source.status === 'failed' || source.status === 'cancelled') && (
              <button
                onClick={() => void retrySource(source.id)}
                className="rounded-md px-2.5 py-1 text-xs text-muted hover:bg-panel hover:text-white"
              >
                Retry
              </button>
            )}
            <button
              onClick={() => {
                if (confirm(`Remove "${name}" from this project?`)) void deleteSource(source.id)
              }}
              className="rounded-md px-2.5 py-1 text-xs text-muted hover:bg-red-950/60 hover:text-red-300"
            >
              Remove
            </button>
          </div>
        </div>

        <div className="mt-auto pt-3">
          {source.status === 'ready' && (
            <div className="mb-2 empty:hidden">
              <AnalysisStatus sourceId={source.id} compact />
            </div>
          )}
          {active ? (
            <>
              <div className="mb-1.5 flex justify-between text-xs text-muted">
                <span>{STAGE_LABELS[source.status]}</span>
                {showPercent && <span>{percent}%</span>}
              </div>
              <div className="h-1.5 overflow-hidden rounded-full bg-black/40">
                <div
                  className={`h-full rounded-full bg-accent transition-[width] duration-300 ${source.status === 'queued' || source.status === 'probing' ? 'animate-pulse' : ''}`}
                  style={{ width: `${Math.max(percent, 3)}%` }}
                />
              </div>
            </>
          ) : source.status === 'failed' ? (
            <div className="text-xs break-words text-red-300">{source.error ?? 'Import failed'}</div>
          ) : source.status === 'cancelled' ? (
            <div className="text-xs text-muted">Import cancelled</div>
          ) : (
            <div className="flex flex-wrap gap-1.5 text-[11px] text-muted">
              {[
                `${source.width}×${source.height}`,
                formatResolution(source.width, source.height),
                formatFps(source.fps),
                formatBytes(source.size_bytes),
                source.video_codec?.toUpperCase(),
                source.has_audio ? source.audio_codec?.toUpperCase() : 'No audio'
              ]
                .filter(Boolean)
                .map((tag) => (
                  <span key={tag} className="rounded bg-black/30 px-1.5 py-0.5">
                    {tag}
                  </span>
                ))}
              {source.is_vfr && (
                <span
                  className="rounded bg-amber-950/60 px-1.5 py-0.5 text-amber-300"
                  title="This video has uneven frame timing (common for phone recordings). The preview uses a steady frame rate so trimming stays frame-accurate."
                >
                  Variable frame rate
                </span>
              )}
            </div>
          )}
        </div>
      </div>
    </li>
  )
}
