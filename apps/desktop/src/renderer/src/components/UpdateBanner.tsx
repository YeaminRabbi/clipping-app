import { useEffect, useState } from 'react'
import type { UpdateStatus } from '../../../shared/types'

/** Shows when a newer version has been downloaded, with a button to restart into it. */
export function UpdateBanner() {
  const [status, setStatus] = useState<UpdateStatus | null>(null)

  useEffect(() => {
    void window.clipping.app.getUpdateStatus().then(setStatus)
    return window.clipping.app.onUpdateStatus(setStatus)
  }, [])

  if (status?.state === 'downloading') {
    return <span className="text-xs text-muted">Downloading update {status.version} · {status.percent ?? 0}%</span>
  }
  if (status?.state !== 'ready') return null
  return (
    <div className="flex items-center gap-2 rounded-full border border-accent/50 bg-accent/15 py-1 pr-1 pl-3 text-xs">
      Version {status.version} is ready
      <button onClick={() => void window.clipping.app.installUpdate()} className="rounded-full bg-accent px-2.5 py-0.5 font-medium hover:bg-accent-hover">
        Restart to update
      </button>
    </div>
  )
}
