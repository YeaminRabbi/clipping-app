import { contextBridge, ipcRenderer, type IpcRendererEvent } from 'electron'
import type { ClippingBridge, EngineStatus } from '../shared/types'

const bridge: ClippingBridge = {
  engine: {
    getStatus: () => ipcRenderer.invoke('engine:get-status'),
    restart: () => ipcRenderer.invoke('engine:restart'),
    onStatus: (listener) => {
      const handler = (_event: IpcRendererEvent, status: EngineStatus): void => listener(status)
      ipcRenderer.on('engine:status', handler)
      return () => ipcRenderer.removeListener('engine:status', handler)
    }
  }
}

contextBridge.exposeInMainWorld('clipping', bridge)
