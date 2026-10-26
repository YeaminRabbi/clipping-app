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

export interface ClippingBridge {
  engine: {
    getStatus(): Promise<EngineStatus>
    restart(): Promise<EngineStatus>
    onStatus(listener: (status: EngineStatus) => void): () => void
  }
}
