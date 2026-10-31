/** Types shared between the main process, preload and renderer. */

export type EngineState = 'starting' | 'ready' | 'error' | 'stopped'

export interface EngineStatus {
  state: EngineState
  /** Base URL of the local engine, e.g. http://127.0.0.1:53211 (set once ready). */
  url: string | null
  /** Per-launch secret the engine requires on every request. */
  token: string | null
  error: string | null
  /** Recent engine output, for showing a useful message when startup fails. */
  logs: string[]
}

export interface UpdateStatus {
  state: 'idle' | 'disabled' | 'checking' | 'up-to-date' | 'downloading' | 'ready' | 'error'
  version: string | null
  percent: number | null
  error: string | null
}

export interface AppInfo {
  version: string
  packaged: boolean
  logsDir: string
}

export interface ClippingBridge {
  app: {
    info(): Promise<AppInfo>
    openLogs(): Promise<void>
    /** Record a renderer error in the app log. */
    reportError(message: string): void
    getUpdateStatus(): Promise<UpdateStatus>
    onUpdateStatus(listener: (status: UpdateStatus) => void): () => void
    checkForUpdates(): Promise<void>
    installUpdate(): Promise<void>
  }
  engine: {
    getStatus(): Promise<EngineStatus>
    restart(): Promise<EngineStatus>
    onStatus(listener: (status: EngineStatus) => void): () => void
  }
  files: {
    /** Show the native file picker for videos. Resolves to the chosen paths (empty if cancelled). */
    pickVideos(): Promise<string[]>
    /** Absolute path of a file dropped onto the window. */
    pathFor(file: File): string
    /** Native folder picker. Resolves to the chosen folder, or null if cancelled. */
    pickFolder(defaultPath?: string): Promise<string | null>
    /** Suggested export folder for a project: Videos/Clipping App/<project>. */
    defaultExportDir(projectName: string): Promise<string>
    /** Reveal a file in Explorer / Finder. */
    showInFolder(path: string): Promise<void>
    /** Open a file or folder with the system's default app. */
    openPath(path: string): Promise<void>
  }
}
