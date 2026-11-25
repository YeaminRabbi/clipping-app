import { FolderOpen, FolderSearch, RotateCcw, RefreshCw } from 'lucide-react'
import { useEffect, useState, type ReactNode } from 'react'
import type { AppInfo, UpdateStatus } from '../../../shared/types'
import { useApp } from '../store'
import { SystemCheck } from './SystemCheck'
import { displayedExportBase, getExportBase, setExportBase } from '../lib/exportFolder'

const dirOf = (path: string): string => path.replace(/[\\/][^\\/]*$/, '')

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="overflow-hidden rounded-2xl border border-line bg-panel shadow-card">
      <h2 className="bg-white/5 px-4 py-3 text-[15px] font-semibold">{title}</h2>
      {children}
    </section>
  )
}

function IconButton({ label, onClick, disabled, children }: { label: string; onClick(): void; disabled?: boolean; children: ReactNode }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      aria-label={label}
      title={label}
      className="not-pill grid size-[34px] shrink-0 place-items-center rounded-full border border-white/20 text-[#c8d1e4] hover:bg-white/10 hover:text-white disabled:opacity-40"
    >
      {children}
    </button>
  )
}

function StorageRow({ label, path, note, children }: { label: string; path: string | null; note?: ReactNode; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5 border-b border-dashed border-[rgba(160,180,220,0.18)] py-3 last:border-b-0">
      <span className="text-sm font-semibold">{label}</span>
      <div className="flex items-center gap-1.5">
        <input
          readOnly
          value={path ?? '—'}
          title={path ?? undefined}
          aria-label={`${label} folder`}
          className="h-[34px] min-w-0 flex-1 rounded-full border border-white/15 bg-[rgba(6,12,26,0.45)] px-3 text-xs text-[#dfe6f5] text-ellipsis outline-none"
        />
        {children}
      </div>
      {note && <span className="text-[11px] leading-relaxed text-muted">{note}</span>}
    </div>
  )
}

function Storage() {
  const health = useApp((s) => s.health)
  const [appInfo, setAppInfo] = useState<AppInfo | null>(null)
  const [exportBase, setExportBaseState] = useState<string | null>(null)
  const [customExports, setCustomExports] = useState(getExportBase() !== null)

  useEffect(() => {
    void window.clipping.app.info().then(setAppInfo)
    void displayedExportBase().then(setExportBaseState)
  }, [])

  const dataDir = health ? dirOf(health.db.path) : null

  const changeExports = async () => {
    const dir = await window.clipping.files.pickFolder(exportBase ?? undefined)
    if (!dir) return
    setExportBase(dir)
    setCustomExports(true)
    setExportBaseState(dir)
  }

  const resetExports = async () => {
    setExportBase(null)
    setCustomExports(false)
    setExportBaseState(await displayedExportBase())
  }

  return (
    <Panel title="Storage">
      <div className="px-4 pb-2">
        <StorageRow
          label="Exports"
          path={exportBase}
          note={customExports ? 'Each project exports into its own folder here. Earlier exports stay where they are.' : 'Each project exports into its own folder here.'}
        >
          <IconButton label="Change export location" onClick={() => void changeExports()}>
            <FolderSearch size={16} strokeWidth={1.6} aria-hidden />
          </IconButton>
          {customExports && (
            <IconButton label="Reset to the default location" onClick={() => void resetExports()}>
              <RotateCcw size={15} strokeWidth={1.6} aria-hidden />
            </IconButton>
          )}
        </StorageRow>
        <StorageRow label="App data" path={dataDir} note="Projects, clips and the database. Moving or clearing it isn't available yet.">
          <IconButton label="Open app data folder" onClick={() => dataDir && void window.clipping.files.openPath(dataDir)} disabled={!dataDir}>
            <FolderOpen size={16} strokeWidth={1.6} aria-hidden />
          </IconButton>
        </StorageRow>
        <StorageRow label="Logs" path={appInfo?.logsDir ?? null}>
          <IconButton label="Open logs folder" onClick={() => void window.clipping.app.openLogs()}>
            <FolderOpen size={16} strokeWidth={1.6} aria-hidden />
          </IconButton>
        </StorageRow>
      </div>
    </Panel>
  )
}

const UPDATE_TEXT: Record<UpdateStatus['state'], string> = {
  idle: 'Updates install only when you choose to.',
  disabled: 'Update checks are off in this build.',
  checking: 'Checking for updates…',
  'up-to-date': 'You have the latest version.',
  available: 'A new version is available.',
  downloading: 'Downloading the update…',
  ready: 'The update is ready. Restart to install it.',
  error: 'The update check failed.'
}

function Updates() {
  const [status, setStatus] = useState<UpdateStatus | null>(null)

  useEffect(() => {
    void window.clipping.app.getUpdateStatus().then(setStatus)
    return window.clipping.app.onUpdateStatus(setStatus)
  }, [])

  const state = status?.state ?? 'idle'
  const busy = state === 'checking' || state === 'downloading'

  return (
    <Panel title="Updates">
      <div className="flex flex-col gap-3 px-4 py-3.5">
        <p className="text-xs leading-relaxed text-muted">
          {UPDATE_TEXT[state]}
          {status?.version && (state === 'available' || state === 'ready') ? ` Version ${status.version}.` : ''}
          {state === 'error' && status?.error ? ` ${status.error}` : ''} Nothing installs without asking you.
        </p>
        <div className="flex flex-wrap gap-2">
          {state === 'available' ? (
            <button onClick={() => void window.clipping.app.downloadUpdate()} className="rounded-md bg-accent px-4 py-1.5 text-sm font-semibold text-on-accent hover:bg-accent-hover">
              Download
            </button>
          ) : state === 'ready' ? (
            <button onClick={() => void window.clipping.app.installUpdate()} className="rounded-md bg-accent px-4 py-1.5 text-sm font-semibold text-on-accent hover:bg-accent-hover">
              Restart to update
            </button>
          ) : (
            <button
              onClick={() => void window.clipping.app.checkForUpdates()}
              disabled={busy || state === 'disabled'}
              className="inline-flex items-center gap-1.5 rounded-md border border-white/20 px-4 py-1.5 text-sm hover:bg-white/10 disabled:opacity-50"
            >
              <RefreshCw size={14} aria-hidden className={busy ? 'animate-spin' : ''} />
              Check now
            </button>
          )}
        </div>
      </div>
    </Panel>
  )
}

/** Settings: system check on the wide side, storage and updates in the narrow column. */
export function SettingsView() {
  return (
    <div className="flex flex-col gap-6 px-8 py-7">
      <div>
        <h1 className="text-3xl font-semibold tracking-[-0.02em]">Settings</h1>
        <p className="mt-1 text-sm text-muted">Check that everything the app needs is working, and where it keeps its files.</p>
      </div>
      <div className="flex flex-wrap items-start gap-4">
        <div className="max-w-full min-w-[520px] flex-[4_1_0%]">
          <SystemCheck />
        </div>
        <div className="flex max-w-full min-w-[280px] flex-[1_1_0%] flex-col gap-4">
          <Storage />
          <Updates />
        </div>
      </div>
    </div>
  )
}
