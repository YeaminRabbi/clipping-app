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
  type Source,
  ACTIVE_STATUSES
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
  /**
   * How many times each clip id has been deleted. SQLite reuses the ids of deleted clips, so editor
   * undo entries remember this count and are dropped once their clip has been deleted since.
   */
  clipDeletions: Record<number, number>
  /** Source (and optional marked range) for the auto-clip dialog; null when it's closed. */
  autoClipDialog: { sourceId: number; range: { start: number; end: number } | null } | null
  /**
   * Videos still importing that should get Find clips as soon as they're ready, with the settings
   * to use. Kept for this session only: after a restart, start Find clips from the video's row.
   */
  autoClipOnReady: Record<number, AnalyzeParams>
  /** The Settings screen is showing (replaces the home / project / editor view). */
  settingsOpen: boolean

  init(): () => void
  restartEngine(): Promise<void>
  refresh(): Promise<void>
  setError(message: string | null): void
  /** Resolves to the new project, or null if it couldn't be created. */
  createProject(name: string): Promise<Project | null>
  deleteProject(id: number): Promise<void>

  openProject(id: number): Promise<void>
  closeProject(): void
  openEditor(sourceId: number): void
  closeEditor(): void

  addUrl(url: string): Promise<boolean>
  /** Adds videos to the open project; resolves to the sources that were added. */
  addFiles(paths: string[]): Promise<Source[]>
  /** Find clips with these settings once the video finishes importing (null turns it off). */
  setAutoClipOnReady(sourceId: number, params: AnalyzeParams | null): void
  openSettings(): void
  /** Back to the projects home: closes Settings, the editor and any open project. */
  goHome(): void
  cancelSource(id: number): Promise<void>
  retrySource(id: number): Promise<void>
  deleteSource(id: number): Promise<void>

  createClip(sourceId: number, startMs: number, endMs: number): Promise<Clip | null>
  updateClip(id: number, patch: Partial<Pick<Clip, 'start_ms' | 'end_ms' | 'title' | 'tighten'>>): Promise<Clip | null>
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

  const clipDeleted = (id: number): void => {
    const { clips, exports, clipDeletions } = get()
    set({
      clips: clips.filter((c) => c.id !== id),
      // The clip's export jobs were deleted with it (and stopped if running).
      exports: exports.filter((j) => j.clip_id !== id),
      clipDeletions: { ...clipDeletions, [id]: (clipDeletions[id] ?? 0) + 1 }
    })
  }

  const onEngineEvent = (event: string, data: unknown): void => {
    const { openProjectId } = get()
    if (event === 'source') {
      const source = data as Source
      if (source.project_id === openProjectId) set({ sources: upsert(get().sources, source) })
      autoClipIfReady(source)
    } else if (event === 'clip') {
      const clip = data as Clip
      if (inOpenProject(clip.source_id)) set({ clips: upsert(get().clips, clip, false).sort(byStart) })
    } else if (event === 'clip_deleted') {
      clipDeleted((data as { id: number }).id)
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
        void run(async (c) => {
          const captionStyle = await c.getCaptionStyle(project_id)
          set({ captionStyle, captionsVersion: get().captionsVersion + 1 })
        })
      }
    } else if (event === 'export') {
      const job = data as ExportJob
      if (job.project_id === openProjectId) set({ exports: upsert(get().exports, job) })
    } else if (event === 'ui_show') {
      // Sent by command-line tools (scripts/clip.mjs) to bring a project or a video into view.
      const { project_id, source_id } = data as { project_id: number; source_id: number | null }
      void (async () => {
        if (project_id !== openProjectId) await get().openProject(project_id)
        // A newer show (or the user) moved to another project while this one loaded.
        if (get().openProjectId !== project_id) return
        // Open the editor only for a video that is loaded and ready; otherwise show the project,
        // where an importing or failed video has its status and controls.
        const ready = get().sources.some((s) => s.id === source_id && s.status === 'ready')
        set({ editorSourceId: ready ? source_id : null, exportDialog: null, autoClipDialog: null })
      })()
    }
  }

  const applyStatus = (engine: EngineStatus): void => {
    const client = EngineClient.from(engine)
    const previous = get().engine
    // A fresh engine connection (first start or after a restart): errors shown before it, such as
    // failed requests while the engine was down, no longer describe the current state.
    const reconnected = client !== null && (previous.url !== engine.url || previous.token !== engine.token)
    unsubscribeEvents?.()
    unsubscribeEvents = client ? client.subscribe(onEngineEvent, () => void get().refresh()) : null
    set({ engine, client, ...(client ? {} : { health: null }), ...(reconnected ? { error: null } : {}) })
    if (client) void get().refresh()
  }

  /** Starts a queued "find clips when ready" run once its video has imported (or drops it if the import failed). */
  const autoClipIfReady = (source: Source): void => {
    const pending = get().autoClipOnReady
    const params = pending[source.id]
    if (!params || ACTIVE_STATUSES.includes(source.status)) return
    const rest = { ...pending }
    delete rest[source.id]
    set({ autoClipOnReady: rest })
    if (source.status === 'ready') void get().analyze(source.id, params)
  }

  const errorMessage = (err: unknown): string => (err instanceof Error ? err.message : String(err))

  /**
   * Run an engine call, surfacing failures in the error banner. Resolves to null if it failed.
   * The banner stays until it's dismissed or a newer error replaces it: clearing it whenever any
   * call started let an unrelated save wipe a message before anyone could read it.
   */
  const run = async <T>(fn: (client: EngineClient) => Promise<T>): Promise<T | null> => {
    const client = get().client
    if (!client) return null
    try {
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
    autoClipOnReady: {},
    settingsOpen: false,
    clipDeletions: {},

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

    createProject: (name) =>
      run(async (client) => {
        const project = await client.createProject(name)
        set({ projects: [project, ...get().projects] })
        return project
      }),

    deleteProject: async (id) => {
      await run(async (client) => {
        await client.deleteProject(id)
        set({ projects: get().projects.filter((p) => p.id !== id) })
      })
    },

    openProject: async (id) => {
      set({ settingsOpen: false, openProjectId: id, editorSourceId: null, sources: [], clips: [], exports: [], analyses: {}, exportBatches: [], captionStyle: null })
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
      const added: Source[] = []
      await run(async (client) => {
        const id = get().openProjectId
        if (id === null) return
        const failures: string[] = []
        // One at a time so each file gets its own error instead of failing the whole batch.
        for (const path of paths) {
          try {
            const source = await client.addSource(id, { path })
            added.push(source)
            set({ sources: upsert(get().sources, source) })
          } catch (err) {
            failures.push(errorMessage(err))
          }
        }
        if (failures.length) throw new Error(failures.join(' · '))
      })
      return added
    },

    setAutoClipOnReady: (sourceId, params) => {
      const rest = { ...get().autoClipOnReady }
      if (params) rest[sourceId] = params
      else delete rest[sourceId]
      set({ autoClipOnReady: rest })
      // The video may already have finished importing.
      const source = get().sources.find((s) => s.id === sourceId)
      if (params && source) autoClipIfReady(source)
    },

    openSettings: () => set({ settingsOpen: true, exportDialog: null, autoClipDialog: null }),

    goHome: () => {
      set({ settingsOpen: false })
      if (get().openProjectId !== null) get().closeProject()
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
        clipDeleted(id)
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
        // The old clip is deleted; the replacement may even get the same id back.
        clipDeleted(id)
        set({ clips: upsert(get().clips, clip, false).sort(byStart) })
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
