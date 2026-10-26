import { create } from 'zustand'
import type { EngineStatus } from '../../shared/types'
import { EngineClient, type Health, type Project } from './lib/api'

interface AppState {
  engine: EngineStatus
  client: EngineClient | null
  health: Health | null
  projects: Project[]
  error: string | null

  init(): () => void
  restartEngine(): Promise<void>
  refresh(): Promise<void>
  createProject(name: string): Promise<void>
  deleteProject(id: number): Promise<void>
}

const initialEngine: EngineStatus = { state: 'starting', url: null, token: null, error: null, logs: [] }

export const useApp = create<AppState>((set, get) => {
  const applyStatus = (engine: EngineStatus): void => {
    set({ engine, client: EngineClient.from(engine), ...(engine.state === 'ready' ? {} : { health: null }) })
    if (engine.state === 'ready') void get().refresh()
  }

  const run = async (fn: () => Promise<void>): Promise<void> => {
    try {
      set({ error: null })
      await fn()
    } catch (err) {
      set({ error: err instanceof Error ? err.message : String(err) })
    }
  }

  return {
    engine: initialEngine,
    client: null,
    health: null,
    projects: [],
    error: null,

    init() {
      const unsubscribe = window.clipping.engine.onStatus(applyStatus)
      void window.clipping.engine.getStatus().then(applyStatus)
      return unsubscribe
    },

    async restartEngine() {
      set({ engine: { ...get().engine, state: 'starting', error: null } })
      applyStatus(await window.clipping.engine.restart())
    },

    refresh: () =>
      run(async () => {
        const client = get().client
        if (!client) return
        const [health, projects] = await Promise.all([client.health(), client.listProjects()])
        set({ health, projects })
      }),

    createProject: (name) =>
      run(async () => {
        const client = get().client
        if (!client) return
        const project = await client.createProject(name)
        set({ projects: [project, ...get().projects] })
      }),

    deleteProject: (id) =>
      run(async () => {
        const client = get().client
        if (!client) return
        await client.deleteProject(id)
        set({ projects: get().projects.filter((p) => p.id !== id) })
      })
  }
})
