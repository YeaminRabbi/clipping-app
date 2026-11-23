import { existsSync, statSync } from 'node:fs'
import { extname, isAbsolute, join } from 'node:path'
import { app, BrowserWindow, dialog, ipcMain, shell, type OpenDialogOptions } from 'electron'
import { EngineProcess } from './engine'
import { log, logsDir } from './log'
import { checkForUpdates, installUpdate, startAutoUpdates, updateStatus } from './updater'

// Development runs keep their own projects and settings, so they never touch the installed app's data.
if (!app.isPackaged) app.setPath('userData', join(app.getPath('appData'), 'Clipping App Dev'))

const engine = new EngineProcess()

const VIDEO_EXTENSIONS = ['mp4', 'mov', 'mkv', 'webm', 'avi', 'm4v', 'wmv', 'flv', 'mts', 'm2ts', 'ts', 'mpg', 'mpeg', '3gp']

function createWindow(): BrowserWindow {
  const win = new BrowserWindow({
    width: 1280,
    height: 820,
    minWidth: 960,
    minHeight: 600,
    show: false,
    backgroundColor: '#0b0d12',
    title: 'Clipping App',
    autoHideMenuBar: true,
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: true
    }
  })

  win.once('ready-to-show', () => win.show())

  // Open external links in the user's browser instead of inside the app.
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (/^https?:\/\//.test(url)) void shell.openExternal(url)
    return { action: 'deny' }
  })

  if (!app.isPackaged && process.env.ELECTRON_RENDERER_URL) {
    void win.loadURL(process.env.ELECTRON_RENDERER_URL)
  } else {
    void win.loadFile(join(__dirname, '../renderer/index.html'))
  }
  return win
}

function registerIpc(): void {
  ipcMain.handle('app:info', () => ({ version: app.getVersion(), packaged: app.isPackaged, logsDir: logsDir() }))
  ipcMain.handle('app:open-logs', async () => {
    await shell.openPath(logsDir())
  })
  ipcMain.on('app:renderer-error', (_event, message: string) => log('error', `renderer: ${message}`))
  ipcMain.handle('update:get-status', () => updateStatus())
  ipcMain.handle('update:check', () => checkForUpdates())
  ipcMain.handle('update:install', () => installUpdate(() => engine.stop()))
  ipcMain.handle('engine:get-status', () => engine.getStatus())
  ipcMain.handle('engine:restart', () => engine.restart())
  ipcMain.handle('files:pick-videos', async (event) => {
    const win = BrowserWindow.fromWebContents(event.sender)
    const options: OpenDialogOptions = {
      title: 'Import videos',
      properties: ['openFile', 'multiSelections'],
      filters: [
        { name: 'Videos', extensions: VIDEO_EXTENSIONS },
        { name: 'All files', extensions: ['*'] }
      ]
    }
    const result = win ? await dialog.showOpenDialog(win, options) : await dialog.showOpenDialog(options)
    return result.canceled ? [] : result.filePaths
  })
  ipcMain.handle('files:pick-folder', async (event, defaultPath?: string) => {
    const win = BrowserWindow.fromWebContents(event.sender)
    const options: OpenDialogOptions = {
      title: 'Choose where to save the clips',
      defaultPath,
      properties: ['openDirectory', 'createDirectory']
    }
    const result = win ? await dialog.showOpenDialog(win, options) : await dialog.showOpenDialog(options)
    return result.canceled ? null : result.filePaths[0]
  })
  ipcMain.handle('files:default-export-dir', (_event, projectName: string) => {
    const safe = String(projectName).replace(/[<>:"/\\|?*\x00-\x1f]/g, '').trim().slice(0, 80) || 'Untitled'
    return join(app.getPath('videos'), 'Clipping App', safe)
  })
  ipcMain.handle('files:show-in-folder', (_event, path: string) => {
    if (isAbsolute(path)) shell.showItemInFolder(path)
  })
  ipcMain.handle('files:open-path', async (_event, path: string) => {
    // Only folders and videos: opening an arbitrary path could launch a program.
    if (!isAbsolute(path) || !existsSync(path)) return
    const isVideo = VIDEO_EXTENSIONS.includes(extname(path).slice(1).toLowerCase())
    if (isVideo || statSync(path).isDirectory()) await shell.openPath(path)
  })
  engine.onStatus((status) => {
    for (const win of BrowserWindow.getAllWindows()) win.webContents.send('engine:status', status)
  })
}

if (!app.requestSingleInstanceLock()) {
  app.quit()
} else {
  app.on('second-instance', () => {
    const win = BrowserWindow.getAllWindows()[0]
    if (win) {
      if (win.isMinimized()) win.restore()
      win.focus()
    }
  })

  process.on('uncaughtException', (err) => log('error', `main: uncaught ${err.stack ?? err}`))
  process.on('unhandledRejection', (reason) => log('error', `main: unhandled rejection ${String(reason)}`))
  app.on('render-process-gone', (_event, _contents, details) => log('error', `renderer process gone: ${details.reason}`))

  app.whenReady().then(() => {
    log('info', `Clipping App ${app.getVersion()} starting (${app.isPackaged ? 'installed' : 'development'})`)
    registerIpc()
    void engine.start()
    createWindow()
    startAutoUpdates()

    app.on('activate', () => {
      if (BrowserWindow.getAllWindows().length === 0) createWindow()
    })
  })

  app.on('window-all-closed', () => {
    if (process.platform !== 'darwin') app.quit()
  })

  app.on('before-quit', () => engine.stop())
}
