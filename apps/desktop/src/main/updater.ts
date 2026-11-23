import { app, BrowserWindow } from 'electron'
import electronUpdater from 'electron-updater'
import type { UpdateStatus } from '../shared/types'
import { log } from './log'

const { autoUpdater } = electronUpdater

const CHECK_EVERY_MS = 6 * 60 * 60 * 1000

let status: UpdateStatus = { state: 'idle', version: null, percent: null, error: null }

function publish(next: Partial<UpdateStatus>): void {
  status = { ...status, ...next }
  for (const win of BrowserWindow.getAllWindows()) win.webContents.send('update:status', status)
}

/** Before the first GitHub release is published there's nothing to update to; that's not an error. */
function isNoReleases(err: unknown): boolean {
  return /No published versions/i.test(err instanceof Error ? err.message : String(err))
}

export function updateStatus(): UpdateStatus {
  return status
}

/**
 * Checks GitHub Releases (configured in electron-builder.yml) for a newer version, downloads it in the
 * background, and lets the user restart into it. Only runs in the installed app.
 */
export function startAutoUpdates(): void {
  if (!app.isPackaged) {
    status = { ...status, state: 'disabled' }
    return
  }
  autoUpdater.autoDownload = true
  autoUpdater.autoInstallOnAppQuit = true
  autoUpdater.logger = {
    info: (m: unknown) => log('info', `updater: ${String(m)}`),
    warn: (m: unknown) => log('warn', `updater: ${String(m)}`),
    // "No releases yet" isn't a problem; anything else is worth recording.
    error: (m: unknown) => !isNoReleases(m) && log('error', `updater: ${String(m)}`),
    debug: () => {}
  }
  autoUpdater.on('checking-for-update', () => publish({ state: 'checking', error: null }))
  autoUpdater.on('update-available', (info) => publish({ state: 'downloading', version: info.version, percent: 0 }))
  autoUpdater.on('update-not-available', () => publish({ state: 'up-to-date' }))
  autoUpdater.on('download-progress', (p) => publish({ state: 'downloading', percent: Math.round(p.percent) }))
  autoUpdater.on('update-downloaded', (info) => publish({ state: 'ready', version: info.version, percent: 100 }))
  autoUpdater.on('error', (err) =>
    publish(isNoReleases(err) ? { state: 'up-to-date', error: null } : { state: 'error', error: err?.message ?? String(err) })
  )

  const check = (): void => {
    autoUpdater.checkForUpdates().catch((err) => !isNoReleases(err) && log('warn', `Update check failed: ${err?.message ?? err}`))
  }
  check()
  setInterval(check, CHECK_EVERY_MS)
}

export function checkForUpdates(): void {
  if (app.isPackaged) autoUpdater.checkForUpdates().catch(() => {})
}

/** Restart into the downloaded update. `beforeQuit` stops the engine first. */
export function installUpdate(beforeQuit: () => void): void {
  if (status.state !== 'ready') return
  beforeQuit()
  autoUpdater.quitAndInstall()
}
