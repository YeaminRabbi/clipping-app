import type { EngineStatus } from '../../../shared/types'

export interface ToolInfo {
  path: string | null
  version: string | null
  source: 'env' | 'bundled' | 'system' | null
}

export interface Health {
  status: 'ok'
  version: string
  db: { path: string; schema_version: number }
  ffmpeg: {
    ok: boolean
    ffmpeg: ToolInfo
    ffprobe: ToolInfo
    hw_encoders: Record<string, string[]>
  }
}

export interface Project {
  id: number
  name: string
  settings: Record<string, unknown>
  created_at: string
  updated_at: string
  source_count: number
}

export type SourceStatus = 'queued' | 'downloading' | 'probing' | 'processing' | 'ready' | 'failed' | 'cancelled'

export const ACTIVE_STATUSES: SourceStatus[] = ['queued', 'downloading', 'probing', 'processing']

export interface Source {
  id: number
  project_id: number
  origin: 'url' | 'file'
  url: string | null
  path: string | null
  title: string | null
  status: SourceStatus
  progress: number
  error: string | null
  duration_ms: number | null
  fps: number | null
  width: number | null
  height: number | null
  size_bytes: number | null
  video_codec: string | null
  audio_codec: string | null
  has_audio: boolean
  is_vfr: boolean
  proxy_url: string | null
  poster_url: string | null
  timeline: SourceTimeline | null
  created_at: string
}

export interface ThumbLayout {
  interval_s: number
  count: number
  cols: number
  rows: number
  tile_w: number
  tile_h: number
}

export interface SourceTimeline {
  thumbs_url: string
  thumbs: ThumbLayout
  waveform_url: string
  peaks_per_second: number
}

/** Rectangle normalized to the source's displayed frame (0..1). */
export interface Crop {
  x: number
  y: number
  w: number
  h: number
}

export type FramingMode = 'manual' | 'smart' | 'fit'

/** A point on a smart-framing path; `t` is source time in ms. */
export interface Keyframe extends Crop {
  t: number
}

export interface FitStyle {
  background: 'blur' | 'black' | 'white'
  dim: number // 0..0.6
  zoom: number // 1..1.5
  position: 'center' | 'top'
}

export const DEFAULT_FIT: FitStyle = { background: 'blur', dim: 0.25, zoom: 1, position: 'center' }

export type FollowMode = 'speaker' | 'largest'

export interface SmartOptions {
  face_ratio?: number // share of the clip where a face was found
  follow?: FollowMode // what was asked for
  followed?: FollowMode // what was done: "speaker" needs two or more people on screen
  speakers?: number
  switches?: number // camera cuts between speakers
}

export interface Tighten {
  remove_fillers: boolean
  remove_pauses: boolean
  max_pause_ms: number
}

export const DEFAULT_TIGHTEN: Tighten = { remove_fillers: true, remove_pauses: true, max_pause_ms: 500 }

export interface CutPlan {
  status: 'off' | 'needs_transcript' | 'ready'
  segments?: [number, number][]
  cuts?: { start: number; end: number; reason: 'filler' | 'pause' }[]
  fillers?: number
  pauses?: number
  duration_ms?: number
  removed_ms?: number
}

export interface ClipFormat {
  id: number
  mode: FramingMode
  crop: Crop | null
  /** Fit: the style. Smart: tracking results (see SmartOptions). */
  options: Partial<FitStyle> & SmartOptions
  /** Smart only: the tracked path, and whether the clip now extends past it. */
  keyframes?: Keyframe[]
  stale?: boolean
}

export interface Clip {
  id: number
  source_id: number
  start_ms: number
  end_ms: number
  title: string
  status: 'suggested' | 'kept' | 'rejected'
  score: number | null
  reasons: string[]
  /** Remove filler words and long pauses (null = off). */
  tighten: Tighten | null
  sort_order: number
  formats: Record<string, ClipFormat>
}

export type CaptionTemplate = 'bold_pop' | 'karaoke' | 'classic' | 'minimal'

export interface CaptionStyle {
  template: CaptionTemplate
  font: string
  size: number // px for a 1920-tall frame
  bold: boolean
  uppercase: boolean
  color: string
  highlight: string
  outline: number
  box: boolean
  position: 'top' | 'middle' | 'bottom'
  max_words: number
  max_chars: number
  max_lines: number
  effect: 'none' | 'pop' | 'karaoke'
}

export type CaptionOverrides = Partial<Pick<CaptionStyle, 'font' | 'size' | 'uppercase' | 'color' | 'highlight' | 'position'>>

export interface CaptionTemplates {
  default: CaptionTemplate
  templates: Record<CaptionTemplate, CaptionStyle>
  fonts: string[]
}

export interface ProjectCaptionStyle {
  template: CaptionTemplate
  overrides: CaptionOverrides
  style: CaptionStyle
}

export interface CaptionWord {
  start: number
  end: number
  text: string
  index: number
}

export interface CaptionCue {
  start: number
  end: number
  text: string
  words: CaptionWord[]
}

export interface ClipCaptions {
  clip_id: number
  status: 'ready' | 'needs_transcript'
  edited: boolean
  cues: CaptionCue[]
  style: CaptionStyle
}

export interface ExportBatch {
  id: string
  project_id: number
  zip: boolean
  zip_path: string | null
  error: string | null
  created_at: string
}

export type AnalysisMode = 'talking' | 'action' | 'even'
export type SpeechModel = 'tiny' | 'base' | 'small'

export interface AnalyzeParams {
  mode: AnalysisMode
  clip_count: number | null
  min_seconds: number
  max_seconds: number
  keywords: string[]
  range_start_ms: number | null
  range_end_ms: number | null
  model: SpeechModel
  language: string | null
}

export interface Analysis {
  source_id: number
  status: 'queued' | 'running' | 'done' | 'failed' | 'cancelled'
  stage: string | null
  progress: number
  error: string | null
  settings: AnalyzeParams
  notes: string[]
  mode_used: AnalysisMode | null
  clip_count: number | null
  /** What's running: finding clips, or only transcribing (for captions). */
  task: 'find_clips' | 'transcribe'
  updated_at: string
}

export interface ExportPreset {
  codec: 'h264' | 'hevc'
  quality: 'high' | 'balanced' | 'small'
  resolution: 1080 | 720
  fps: 'source' | '30' | '60'
  hardware: boolean
  /** Framing for sizes that weren't set up in the editor. */
  default_framing: 'smart' | 'center' | 'fit'
  captions: 'off' | 'burn' | 'burn_srt' | 'srt'
  zip: boolean
  /** Tighten clips that don't have their own setting. */
  tighten_all: boolean
  output_dir: string
  name_template: string
}

export type ExportStatus = 'queued' | 'rendering' | 'done' | 'failed' | 'cancelled'

export interface ExportJob {
  id: number
  project_id: number
  source_id: number
  clip_id: number
  clip_title: string
  aspect: string
  mode: string
  status: ExportStatus
  progress: number
  output_name: string
  output_path: string | null
  encoder: string | null
  error: string | null
  preset: ExportPreset
  batch_id: string | null
  burn_captions: boolean
  export_srt: boolean
  srt_path: string | null
  created_at: string
}

export class EngineClient {
  constructor(
    private readonly baseUrl: string,
    private readonly token: string
  ) {}

  static from(status: EngineStatus): EngineClient | null {
    return status.state === 'ready' && status.url && status.token ? new EngineClient(status.url, status.token) : null
  }

  private async request<T>(path: string, init: RequestInit = {}): Promise<T> {
    const res = await fetch(this.baseUrl + path, {
      ...init,
      headers: { 'content-type': 'application/json', 'x-engine-token': this.token, ...init.headers }
    })
    if (!res.ok) {
      let detail = res.statusText
      try {
        const body = await res.json()
        detail =
          typeof body.detail === 'string'
            ? body.detail
            : Array.isArray(body.detail)
              ? body.detail.map((e: { msg?: string }) => e.msg ?? JSON.stringify(e)).join('; ')
              : JSON.stringify(body.detail)
      } catch {
        // Keep the status text when the body isn't JSON.
      }
      throw new Error(detail)
    }
    return (res.status === 204 ? undefined : await res.json()) as T
  }

  health(): Promise<Health> {
    return this.request('/health')
  }

  listProjects(): Promise<Project[]> {
    return this.request('/projects')
  }

  createProject(name: string): Promise<Project> {
    return this.request('/projects', { method: 'POST', body: JSON.stringify({ name }) })
  }

  deleteProject(id: number): Promise<void> {
    return this.request(`/projects/${id}`, { method: 'DELETE' })
  }

  listSources(projectId: number): Promise<Source[]> {
    return this.request(`/projects/${projectId}/sources`)
  }

  addSource(projectId: number, input: { url: string } | { path: string }): Promise<Source> {
    return this.request(`/projects/${projectId}/sources`, { method: 'POST', body: JSON.stringify(input) })
  }

  cancelSource(id: number): Promise<Source> {
    return this.request(`/sources/${id}/cancel`, { method: 'POST' })
  }

  retrySource(id: number): Promise<Source> {
    return this.request(`/sources/${id}/retry`, { method: 'POST' })
  }

  deleteSource(id: number): Promise<void> {
    return this.request(`/sources/${id}`, { method: 'DELETE' })
  }

  listProjectClips(projectId: number): Promise<Clip[]> {
    return this.request(`/projects/${projectId}/clips`)
  }

  createClip(sourceId: number, body: { start_ms: number; end_ms: number; title?: string }): Promise<Clip> {
    return this.request(`/sources/${sourceId}/clips`, { method: 'POST', body: JSON.stringify(body) })
  }

  updateClip(id: number, body: Partial<Pick<Clip, 'start_ms' | 'end_ms' | 'title' | 'status' | 'tighten'>>): Promise<Clip> {
    return this.request(`/clips/${id}`, { method: 'PATCH', body: JSON.stringify(body) })
  }

  setClipFormat(
    id: number,
    aspect: string,
    body: { mode: FramingMode; crop?: Crop | null; fit?: FitStyle; follow?: FollowMode }
  ): Promise<Clip> {
    return this.request(`/clips/${id}/formats/${aspect.replace(':', 'x')}`, { method: 'PUT', body: JSON.stringify(body) })
  }

  getCutPlan(clipId: number): Promise<CutPlan> {
    return this.request(`/clips/${clipId}/cut-plan`)
  }

  deleteClip(id: number): Promise<void> {
    return this.request(`/clips/${id}`, { method: 'DELETE' })
  }

  analyze(sourceId: number, params: AnalyzeParams): Promise<Analysis> {
    return this.request(`/sources/${sourceId}/analyze`, { method: 'POST', body: JSON.stringify(params) })
  }

  listAnalyses(projectId: number): Promise<Analysis[]> {
    return this.request(`/projects/${projectId}/analyses`)
  }

  cancelAnalysis(sourceId: number): Promise<Analysis> {
    return this.request(`/sources/${sourceId}/analysis/cancel`, { method: 'POST' })
  }

  replaceClip(id: number): Promise<Clip> {
    return this.request(`/clips/${id}/replace`, { method: 'POST' })
  }

  captionTemplates(): Promise<CaptionTemplates> {
    return this.request('/caption-templates')
  }

  getCaptionStyle(projectId: number): Promise<ProjectCaptionStyle> {
    return this.request(`/projects/${projectId}/caption-style`)
  }

  setCaptionStyle(projectId: number, template: CaptionTemplate, overrides: CaptionOverrides): Promise<ProjectCaptionStyle> {
    return this.request(`/projects/${projectId}/caption-style`, { method: 'PUT', body: JSON.stringify({ template, overrides }) })
  }

  getCaptions(clipId: number): Promise<ClipCaptions> {
    return this.request(`/clips/${clipId}/captions`)
  }

  editCaption(clipId: number, indices: number[], text: string): Promise<ClipCaptions> {
    return this.request(`/clips/${clipId}/captions/edit`, { method: 'POST', body: JSON.stringify({ indices, text }) })
  }

  resetCaptions(clipId: number): Promise<ClipCaptions> {
    return this.request(`/clips/${clipId}/captions`, { method: 'DELETE' })
  }

  transcribe(sourceId: number, model: SpeechModel, language: string | null): Promise<Analysis> {
    return this.request(`/sources/${sourceId}/transcribe`, { method: 'POST', body: JSON.stringify({ model, language }) })
  }

  listExportBatches(projectId: number): Promise<ExportBatch[]> {
    return this.request(`/projects/${projectId}/export-batches`)
  }

  createExports(body: { clip_ids: number[]; aspects: string[]; preset: ExportPreset }): Promise<ExportJob[]> {
    return this.request('/exports', { method: 'POST', body: JSON.stringify(body) })
  }

  listExports(projectId: number): Promise<ExportJob[]> {
    return this.request(`/projects/${projectId}/exports`)
  }

  cancelExport(id: number): Promise<ExportJob> {
    return this.request(`/exports/${id}/cancel`, { method: 'POST' })
  }

  retryExport(id: number): Promise<ExportJob> {
    return this.request(`/exports/${id}/retry`, { method: 'POST' })
  }

  clearFinishedExports(projectId: number): Promise<void> {
    return this.request(`/projects/${projectId}/exports`, { method: 'DELETE' })
  }

  async waveform(path: string): Promise<Uint8Array> {
    const res = await fetch(this.mediaUrl(path))
    if (!res.ok) throw new Error('Waveform unavailable')
    return new Uint8Array(await res.arrayBuffer())
  }

  /** Full URL for engine-served media, usable in <video> / <img> (which can't send headers). */
  mediaUrl(path: string): string {
    return `${this.baseUrl}${path}?token=${this.token}`
  }

  /** Subscribe to engine events (job progress etc.). Returns a function that closes the socket. */
  subscribe(onEvent: (event: string, data: unknown) => void): () => void {
    const ws = new WebSocket(`${this.baseUrl.replace(/^http/, 'ws')}/ws?token=${this.token}`)
    ws.onmessage = (msg) => {
      try {
        const { event, data } = JSON.parse(msg.data)
        onEvent(event, data)
      } catch {
        // Ignore malformed frames.
      }
    }
    return () => ws.close()
  }
}
