import { contextBridge, ipcRenderer, webUtils, type IpcRendererEvent } from 'electron'
import type { ClippingBridge, EngineStatus, UpdateStatus } from '../shared/types'

const bridge: ClippingBridge = {
  app: {
    info: () => ipcRenderer.invoke('app:info'),
    openLogs: () => ipcRenderer.invoke('app:open-logs'),
    reportError: (message) => ipcRenderer.send('app:renderer-error', String(message).slice(0, 4000)),
    getUpdateStatus: () => ipcRenderer.invoke('update:get-status'),
    onUpdateStatus: (listener) => {
      const handler = (_event: IpcRendererEvent, status: UpdateStatus): void => listener(status)
      ipcRenderer.on('update:status', handler)
      return () => ipcRenderer.removeListener('update:status', handler)
    },
    checkForUpdates: () => ipcRenderer.invoke('update:check'),
    installUpdate: () => ipcRenderer.invoke('update:install')
  },
  engine: {
    getStatus: () => ipcRenderer.invoke('engine:get-status'),
    restart: () => ipcRenderer.invoke('engine:restart'),
    onStatus: (listener) => {
      const handler = (_event: IpcRendererEvent, status: EngineStatus): void => listener(status)
      ipcRenderer.on('engine:status', handler)
      return () => ipcRenderer.removeListener('engine:status', handler)
    }
  },
  files: {
    pickVideos: () => ipcRenderer.invoke('files:pick-videos'),
    pathFor: (file) => webUtils.getPathForFile(file),
    pickFolder: (defaultPath) => ipcRenderer.invoke('files:pick-folder', defaultPath),
    defaultExportDir: (projectName) => ipcRenderer.invoke('files:default-export-dir', projectName),
    showInFolder: (path) => ipcRenderer.invoke('files:show-in-folder', path),
    openPath: (path) => ipcRenderer.invoke('files:open-path', path)
  }
}

contextBridge.exposeInMainWorld('clipping', bridge)
