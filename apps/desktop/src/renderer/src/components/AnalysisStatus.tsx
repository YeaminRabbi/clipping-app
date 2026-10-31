import { useApp } from '../store'

/** Progress, result notes or error of the latest auto-clip run for a source. Renders nothing when idle. */
export function AnalysisStatus({ sourceId, compact = false }: { sourceId: number; compact?: boolean }) {
  const analysis = useApp((s) => s.analyses[sourceId])
  const { cancelAnalysis, openAutoClipDialog } = useApp.getState()
  if (!analysis) return null

  if (analysis.status === 'queued' || analysis.status === 'running') {
    const percent = Math.round(analysis.progress * 100)
    return (
      <div className="rounded-md border border-accent/40 bg-accent/10 px-3 py-2">
        <div className="flex items-center justify-between gap-3 text-xs">
          <span>
            {analysis.task === 'transcribe' ? 'Transcribing' : 'Finding clips'}: {analysis.stage ?? 'starting'}
            {analysis.stage?.startsWith('Downloading') ? '' : ` · ${percent}%`}
          </span>
          <button onClick={() => void cancelAnalysis(sourceId)} className="text-muted hover:text-white">
            Cancel
          </button>
        </div>
        <div className="mt-1.5 h-1 overflow-hidden rounded-full bg-black/40">
          <div
            className={`h-full rounded-full bg-accent transition-[width] duration-300 ${analysis.stage?.startsWith('Downloading') ? 'animate-pulse' : ''}`}
            style={{ width: `${Math.max(percent, 3)}%` }}
          />
        </div>
      </div>
    )
  }

  if (analysis.status === 'failed') {
    return (
      <div className="flex items-start justify-between gap-3 rounded-md border border-red-900/60 bg-red-950/40 px-3 py-2 text-xs text-red-300">
        <span className="break-words">Couldn’t find clips: {analysis.error}</span>
        <button onClick={() => openAutoClipDialog(sourceId)} className="shrink-0 text-red-200 hover:text-white">
          Try again
        </button>
      </div>
    )
  }

  if (analysis.status === 'done' && !compact && analysis.notes.length > 0) {
    return (
      <div className="rounded-md border border-amber-900/50 bg-amber-950/30 px-3 py-2 text-xs text-amber-200">
        {analysis.notes.join(' ')}
      </div>
    )
  }
  return null
}
