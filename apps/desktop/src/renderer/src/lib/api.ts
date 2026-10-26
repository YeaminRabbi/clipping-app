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
        detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
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
