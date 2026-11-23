import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { app, BrowserWindow, dialog, type MessageBoxOptions } from 'electron'
import electronUpdater from 'electron-updater'
import type { UpdateStatus } from '../shared/types'
import { log } from './log'
import { updatePolicy, type UpdatePolicy } from './updatePolicy'

const { autoUpdater } = electronUpdater

const CHECK_EVERY_MS = 6 * 60 * 60 * 1000

let status: UpdateStatus = { state: 'idle', version: null, percent: null, error: null }
let policy: UpdatePolicy = updatePolicy(null)

function loadPolicy(): UpdatePolicy {
  try {
    return updatePolicy(readFileSync(join(process.resourcesPath, 'app-update.yml'), 'utf8'))
  } catch {
    return updatePolicy(null)
  }
}

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
 * Checks GitHub Releases (configured in electron-builder.yml) for a newer version. Signed builds
 * download it in the background and let the user restart into it; unsigned builds only say there is
 * one, and download and install it when the user asks and confirms. Only runs in the installed app.
 */
export function startAutoUpdates(): void {
  if (!app.isPackaged) {
    status = { ...status, state: 'disabled' }
    return
  }
  policy = loadPolicy()
  autoUpdater.autoDownload = policy.autoDownload
  autoUpdater.autoInstallOnAppQuit = policy.autoInstallOnAppQuit
  if (!policy.verified) log('info', 'updater: this build is not signed, so updates are never downloaded or installed automatically')
  autoUpdater.logger = {
    info: (m: unknown) => log('info', `updater: ${String(m)}`),
    warn: (m: unknown) => log('warn', `updater: ${String(m)}`),
    // "No releases yet" isn't a problem; anything else is worth recording.
    error: (m: unknown) => !isNoReleases(m) && log('error', `updater: ${String(m)}`),
    debug: () => {}
  }
  autoUpdater.on('checking-for-update', () => publish({ state: 'checking', error: null }))
  autoUpdater.on('update-available', (info) =>
    publish({ state: policy.autoDownload ? 'downloading' : 'available', version: info.version, percent: policy.autoDownload ? 0 : null })
  )
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

/** Download the available update because the user asked to (unsigned builds only; signed ones already did). */
export function downloadUpdate(): void {
  if (status.state !== 'available') return
  publish({ state: 'downloading', percent: 0 })
  autoUpdater.downloadUpdate().catch((err) => publish({ state: 'error', error: err?.message ?? String(err) }))
}

async function confirmUnverified(win: BrowserWindow | null): Promise<boolean> {
  const options: MessageBoxOptions = {
    type: 'warning',
    title: 'Install an unverified update?',
    message: `Install version ${status.version ?? ''}?`,
    detail:
      "This app isn't code-signed, so it can't check who made this update. Install it only if you were expecting it and trust the project's GitHub releases.",
    buttons: ['Cancel', 'Install'],
    defaultId: 0,
    cancelId: 0,
    noLink: true
  }
  const result = win ? await dialog.showMessageBox(win, options) : await dialog.showMessageBox(options)
  return result.response === 1
}

/** Restart into the downloaded update, after confirming if it can't be verified. `beforeQuit` stops the engine first. */
export async function installUpdate(win: BrowserWindow | null, beforeQuit: () => void): Promise<void> {
  if (status.state !== 'ready') return
  if (!policy.verified && !(await confirmUnverified(win))) return
  beforeQuit()
  autoUpdater.quitAndInstall()
}
