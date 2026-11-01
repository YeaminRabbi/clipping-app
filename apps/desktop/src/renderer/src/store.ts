import { create } from 'zustand'
import type { EngineStatus } from '../../shared/types'
import {
  EngineClient,
  type Analysis,
  type AnalyzeParams,
  type Clip,
  type Crop,
  type ExportBatch,
  type ExportJob,
  type CaptionOverrides,
  type CaptionTemplate,
  type CaptionTemplates,
  type ProjectCaptionStyle,
  type ExportPreset,
  type FitStyle,
  type FollowMode,
  type FramingMode,
  type Health,
  type Project,
  type Source
} from './lib/api'

interface AppState {
  engine: EngineStatus
  client: EngineClient | null
  health: Health | null
  projects: Project[]
  error: string | null

  /** Project currently open, or null for the home screen. */
  openProjectId: number | null
  /** Source open in the editor, or null for the project overview. */
  editorSourceId: number | null
  sources: Source[]
  clips: Clip[]
  exports: ExportJob[]
  /** Clip ids to preselect when the export dialog is open; null when it's closed. */
  exportDialog: number[] | null
  /** Latest auto-clip analysis per source id. */
  analyses: Record<number, Analysis>
  /** ZIP batches for the open project. */
  exportBatches: ExportBatch[]
  /** Caption templates and fonts (loaded once) and the open project's caption style. */
  captionTemplates: CaptionTemplates | null
  captionStyle: ProjectCaptionStyle | null
  /** Bumped whenever caption inputs change (transcript, style), so caption views refetch. */
  captionsVersion: number
  /** Source (and optional marked range) for the auto-clip dialog; null when it's closed. */
  autoClipDialog: { sourceId: number; range: { start: number; end: number } | null } | null

  init(): () => void
  restartEngine(): Promise<void>
  refresh(): Promise<void>
  setError(message: string | null): void
  createProject(name: string): Promise<void>
  deleteProject(id: number): Promise<void>

  openProject(id: number): Promise<void>
  closeProject(): void
  openEditor(sourceId: number): void
  closeEditor(): void

  addUrl(url: string): Promise<boolean>
  addFiles(paths: string[]): Promise<void>
  cancelSource(id: number): Promise<void>
  retrySource(id: number): Promise<void>
  deleteSource(id: number): Promise<void>

  createClip(sourceId: number, startMs: number, endMs: number): Promise<Clip | null>
  updateClip(id: number, patch: Partial<Pick<Clip, 'start_ms' | 'end_ms' | 'title' | 'tighten' | 'audio'>>): Promise<Clip | null>
  setClipFormat(id: number, aspect: string, mode: FramingMode, crop: Crop | null, fit?: FitStyle, follow?: FollowMode): Promise<Clip | null>
  deleteClip(id: number): Promise<void>

  openAutoClipDialog(sourceId: number, range?: { start: number; end: number } | null): void
  closeAutoClipDialog(): void
  analyze(sourceId: number, params: AnalyzeParams): Promise<boolean>
  cancelAnalysis(sourceId: number): Promise<void>
  replaceClip(id: number): Promise<Clip | null>

  openExportDialog(clipIds: number[]): void
  closeExportDialog(): void
  startExport(clipIds: number[], aspects: string[], preset: ExportPreset): Promise<boolean>
  cancelExport(id: number): Promise<void>
  setCaptionStyle(template: CaptionTemplate, overrides: CaptionOverrides): Promise<void>
  transcribe(sourceId: number, model: 'tiny' | 'base' | 'small', language: string | null): Promise<boolean>
  retryExport(id: number): Promise<void>
  clearFinishedExports(): Promise<void>
}

const initialEngine: EngineStatus = { state: 'starting', url: null, token: null, error: null, logs: [] }

function upsert<T extends { id: number }>(list: T[], item: T, prepend = true): T[] {
  if (list.some((x) => x.id === item.id)) return list.map((x) => (x.id === item.id ? item : x))
  return prepend ? [item, ...list] : [...list, item]
}

function upsertBatch(list: ExportBatch[], batch: ExportBatch): ExportBatch[] {
  return list.some((b) => b.id === batch.id) ? list.map((b) => (b.id === batch.id ? batch : b)) : [batch, ...list]
}

const byStart = (a: Clip, b: Clip): number => a.source_id - b.source_id || a.start_ms - b.start_ms || a.id - b.id

export const useApp = create<AppState>((set, get) => {
  let unsubscribeEvents: (() => void) | null = null

  const inOpenProject = (sourceId: number): boolean => get().sources.some((s) => s.id === sourceId)

  const onEngineEvent = (event: string, data: unknown): void => {
    const { openProjectId } = get()
    if (event === 'source') {
      const source = data as Source
      if (source.project_id === openProjectId) set({ sources: upsert(get().sources, source) })
    } else if (event === 'clip') {
      const clip = data as Clip
      if (inOpenProject(clip.source_id)) set({ clips: upsert(get().clips, clip, false).sort(byStart) })
    } else if (event === 'clip_deleted') {
      const { id } = data as { id: number }
      set({ clips: get().clips.filter((c) => c.id !== id) })
    } else if (event === 'analysis') {
      const analysis = data as Analysis
      if (inOpenProject(analysis.source_id)) set({ analyses: { ...get().analyses, [analysis.source_id]: analysis } })
    } else if (event === 'export_batch') {
      const batch = data as ExportBatch
      if (batch.project_id === openProjectId) set({ exportBatches: upsertBatch(get().exportBatches, batch) })
    } else if (event === 'transcript') {
      set({ captionsVersion: get().captionsVersion + 1 })
    } else if (event === 'caption_style') {
      const { project_id } = data as { project_id: number }
      const client = get().client
      if (project_id === openProjectId && client) {
        void client.getCaptionStyle(project_id).then((captionStyle) => set({ captionStyle, captionsVersion: get().captionsVersion + 1 }))
      }
    } else if (event === 'export') {
      const job = data as ExportJob
      if (job.project_id === openProjectId) set({ exports: upsert(get().exports, job) })
    }
  }

  const applyStatus = (engine: EngineStatus): void => {
    const client = EngineClient.from(engine)
    unsubscribeEvents?.()
    unsubscribeEvents = client ? client.subscribe(onEngineEvent) : null
    set({ engine, client, ...(client ? {} : { health: null }) })
    if (client) void get().refresh()
  }

  const errorMessage = (err: unknown): string => (err instanceof Error ? err.message : String(err))

  /** Run an engine call, surfacing failures in the error banner. Resolves to null if it failed. */
  const run = async <T>(fn: (client: EngineClient) => Promise<T>): Promise<T | null> => {
    const client = get().client
    if (!client) return null
    try {
      set({ error: null })
      return await fn(client)
    } catch (err) {
      set({ error: errorMessage(err) })
      return null
    }
  }

  const loadProjectData = async (client: EngineClient): Promise<void> => {
    const id = get().openProjectId
    if (id === null) return
    const [sources, clips, exports, analysisList, exportBatches, captionStyle, captionTemplates] = await Promise.all([
      client.listSources(id),
      client.listProjectClips(id),
      client.listExports(id),
      client.listAnalyses(id),
      client.listExportBatches(id),
      client.getCaptionStyle(id),
      get().captionTemplates ? Promise.resolve(get().captionTemplates) : client.captionTemplates()
    ])
    const analyses = Object.fromEntries(analysisList.map((a) => [a.source_id, a]))
    if (get().openProjectId === id) set({ sources, clips, exports, analyses, exportBatches, captionStyle, captionTemplates })
  }

  return {
    engine: initialEngine,
    client: null,
    health: null,
    projects: [],
    error: null,
    openProjectId: null,
    editorSourceId: null,
    sources: [],
    clips: [],
    exports: [],
    exportDialog: null,
    analyses: {},
    exportBatches: [],
    captionTemplates: null,
    captionStyle: null,
    captionsVersion: 0,
    autoClipDialog: null,

    init() {
      const unsubscribe = window.clipping.engine.onStatus(applyStatus)
      void window.clipping.engine.getStatus().then(applyStatus)
      return () => {
        unsubscribe()
        unsubscribeEvents?.()
      }
    },

    async restartEngine() {
      set({ engine: { ...get().engine, state: 'starting', error: null } })
      applyStatus(await window.clipping.engine.restart())
    },

    refresh: async () => {
      await run(async (client) => {
        const [health, projects] = await Promise.all([client.health(), client.listProjects()])
        set({ health, projects })
        // Picks up changes missed while the engine was restarting.
        await loadProjectData(client)
      })
    },

    setError: (message) => set({ error: message }),

    createProject: async (name) => {
      await run(async (client) => {
        const project = await client.createProject(name)
        set({ projects: [project, ...get().projects] })
      })
    },

    deleteProject: async (id) => {
      await run(async (client) => {
        await client.deleteProject(id)
        set({ projects: get().projects.filter((p) => p.id !== id) })
      })
    },

    openProject: async (id) => {
      set({ openProjectId: id, editorSourceId: null, sources: [], clips: [], exports: [], analyses: {}, exportBatches: [], captionStyle: null })
      await run(loadProjectData)
    },

    closeProject: () => {
      set({
        openProjectId: null,
        editorSourceId: null,
        sources: [],
        clips: [],
        exports: [],
        analyses: {},
        exportBatches: [],
        captionStyle: null,
        exportDialog: null,
        autoClipDialog: null
      })
      void get().refresh()
    },

    openEditor: (sourceId) => set({ editorSourceId: sourceId }),
    closeEditor: () => set({ editorSourceId: null }),

    addUrl: async (url) =>
      (await run(async (client) => {
        const id = get().openProjectId
        if (id === null) return false
        set({ sources: upsert(get().sources, await client.addSource(id, { url })) })
        return true
      })) ?? false,

    addFiles: async (paths) => {
      await run(async (client) => {
        const id = get().openProjectId
        if (id === null) return
        const failures: string[] = []
        // One at a time so each file gets its own error instead of failing the whole batch.
        for (const path of paths) {
          try {
            set({ sources: upsert(get().sources, await client.addSource(id, { path })) })
          } catch (err) {
            failures.push(errorMessage(err))
          }
        }
        if (failures.length) throw new Error(failures.join(' · '))
      })
    },

    cancelSource: async (id) => {
      await run((client) => client.cancelSource(id))
    },

    retrySource: async (id) => {
      await run(async (client) => set({ sources: upsert(get().sources, await client.retrySource(id)) }))
    },

    deleteSource: async (id) => {
      await run(async (client) => {
        await client.deleteSource(id)
        set({ sources: get().sources.filter((s) => s.id !== id), clips: get().clips.filter((c) => c.source_id !== id) })
      })
    },

    createClip: (sourceId, startMs, endMs) =>
      run(async (client) => {
        const clip = await client.createClip(sourceId, { start_ms: startMs, end_ms: endMs })
        set({ clips: upsert(get().clips, clip, false).sort(byStart) })
        return clip
      }),

    updateClip: (id, patch) =>
      run(async (client) => {
        const clip = await client.updateClip(id, patch)
        set({ clips: upsert(get().clips, clip, false).sort(byStart) })
        return clip
      }),

    setClipFormat: (id, aspect, mode, crop, fit, follow) =>
      run(async (client) => {
        const clip = await client.setClipFormat(id, aspect, { mode, crop, ...(fit ? { fit } : {}), ...(follow ? { follow } : {}) })
        set({ clips: upsert(get().clips, clip, false) })
        return clip
      }),

    deleteClip: async (id) => {
      await run(async (client) => {
        await client.deleteClip(id)
        set({ clips: get().clips.filter((c) => c.id !== id) })
      })
    },

    openAutoClipDialog: (sourceId, range = null) => set({ autoClipDialog: { sourceId, range } }),
    closeAutoClipDialog: () => set({ autoClipDialog: null }),

    analyze: async (sourceId, params) =>
      (await run(async (client) => {
        const analysis = await client.analyze(sourceId, params)
        set({ analyses: { ...get().analyses, [sourceId]: analysis } })
        return true
      })) ?? false,

    cancelAnalysis: async (sourceId) => {
      await run((client) => client.cancelAnalysis(sourceId))
    },

    replaceClip: (id) =>
      run(async (client) => {
        const clip = await client.replaceClip(id)
        set({ clips: upsert(get().clips.filter((c) => c.id !== id), clip, false).sort(byStart) })
        return clip
      }),

    openExportDialog: (clipIds) => set({ exportDialog: clipIds }),
    closeExportDialog: () => set({ exportDialog: null }),

    startExport: async (clipIds, aspects, preset) =>
      (await run(async (client) => {
        const jobs = await client.createExports({ clip_ids: clipIds, aspects, preset })
        let exports = get().exports
        for (const job of jobs) exports = upsert(exports, job)
        set({ exports })
        return true
      })) ?? false,

    setCaptionStyle: async (template, overrides) => {
      await run(async (client) => {
        const id = get().openProjectId
        if (id === null) return
        set({ captionStyle: await client.setCaptionStyle(id, template, overrides), captionsVersion: get().captionsVersion + 1 })
      })
    },

    transcribe: async (sourceId, model, language) =>
      (await run(async (client) => {
        const analysis = await client.transcribe(sourceId, model, language)
        set({ analyses: { ...get().analyses, [sourceId]: analysis } })
        return true
      })) ?? false,

    cancelExport: async (id) => {
      await run((client) => client.cancelExport(id))
    },

    retryExport: async (id) => {
      await run(async (client) => set({ exports: upsert(get().exports, await client.retryExport(id)) }))
    },

    clearFinishedExports: async () => {
      await run(async (client) => {
        const id = get().openProjectId
        if (id === null) return
        await client.clearFinishedExports(id)
        set({ exports: get().exports.filter((j) => j.status === 'queued' || j.status === 'rendering') })
      })
    }
  }
})
