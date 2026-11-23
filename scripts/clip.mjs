#!/usr/bin/env node
// Drive the running Clipping App from the command line: import videos, make and frame clips,
// export, and bring things into view in the window. Built for coding agents (Claude Code, Codex),
// so a task takes a few commands instead of clicking through the UI.
//
// It talks to the engine of the open app window, using the address and token the app writes to
// <app data>/engine.json while the engine runs. The window updates live as commands run.
//
// Output: the result of each command is JSON on stdout; progress and errors go to stderr.
// Exit code: 0 ok, 1 failed (including a job that failed), 2 bad usage, 3 app not running.
//
// Run `node scripts/clip.mjs help` for the commands. (`npm run -s clip -- ...` also works; without -s,
// npm prints its own banner on stdout, which breaks JSON parsing.)
import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync, readFileSync, rmSync } from 'node:fs'
import { homedir, tmpdir } from 'node:os'
import { isAbsolute, join, resolve } from 'node:path'
import { binDir, exe } from './paths.mjs'

const HELP = `Usage: node scripts/clip.mjs <command> [args] [--options]

Times accept 83.5, 1:23.5 or 1:02:03. Ids are numbers printed by earlier commands.

  status                                  Engine address, version, FFmpeg
  projects                                List projects
  project new <name>                      Create a project
  project <id>                            A project with its videos and clips
  import <projectId> <file|url>... [--wait]
                                          Add videos (local files or links)
  sources <projectId>                     List a project's videos
  analyze <sourceId> [--mode talking|action|even] [--count N] [--min S] [--max S]
                     [--keywords a,b] [--wait]
                                          Find clips automatically
  clips <projectId>                       List a project's clips
  clip add <sourceId> <start> <end> [--title T]
  clip set <clipId> [--start T] [--end T] [--title T]
  clip frame <clipId> <aspect> <manual|smart|fit> [--crop x,y,w,h] [--follow speaker|largest]
                     [--background blur|black|white] [--zoom 1..1.5] [--position center|top]
                                          Framing for one size (crop is 0..1 of the frame)
  clip rm <clipId>
  export <clipId>... [--aspect 9:16[,1:1]] [--out DIR] [--framing smart|center|fit]
                     [--captions off|burn|srt|burn_srt] [--quality high|balanced|small]
                     [--resolution 1080|720] [--name TEMPLATE] [--wait]
                                          Render clips (default 9:16, smart framing)
  exports <projectId>                     List a project's exports
  wait source|export|analysis <id>...     Wait until the jobs finish
  show <projectId> | show --source <id>   Bring a project, or a video in the editor, into view
  preview <video> [--count 6] [--out FILE.jpg]
                                          One contact-sheet image of frames from a video, to check output
  api <GET|POST|PUT|PATCH|DELETE> <path> [json]
                                          Any engine endpoint (see AGENTS.md)
`

class UsageError extends Error {}
class NotRunning extends Error {}

// --- arguments ----------------------------------------------------------------------------------

function parseArgs(argv) {
  const positional = []
  const options = {}
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i]
    if (arg.startsWith('--')) {
      const [key, inline] = arg.slice(2).split(/=(.*)/s)
      if (inline !== undefined) options[key] = inline
      else if (i + 1 < argv.length && !argv[i + 1].startsWith('--')) options[key] = argv[++i]
      else options[key] = true
    } else {
      positional.push(arg)
    }
  }
  return { positional, options }
}

function need(value, what) {
  if (value === undefined || value === true || value === '') throw new UsageError(`Missing ${what}. Run "node scripts/clip.mjs help".`)
  return value
}

function id(value, what) {
  const n = Number(need(value, what))
  if (!Number.isInteger(n) || n <= 0) throw new UsageError(`${what} must be a number, got "${value}"`)
  return n
}

/** "83.5", "1:23.5", "1:02:03" or "83.5s" -> milliseconds. */
function toMs(value, what) {
  const text = String(need(value, what)).trim().replace(/s$/, '')
  const raw = text.split(':')
  // Number('') is 0, so empty parts ("1:", ":30") must be rejected before converting.
  const parts = raw.map(Number)
  if (raw.length > 3 || raw.some((p) => p.trim() === '') || parts.some((p) => !Number.isFinite(p) || p < 0)) {
    throw new UsageError(`Can't read ${what} "${value}"`)
  }
  return Math.round(parts.reduce((total, part) => total * 60 + part, 0) * 1000)
}

const list = (value) => (value === undefined || value === true ? [] : String(value).split(',').map((s) => s.trim()).filter(Boolean))

// --- connection ---------------------------------------------------------------------------------

function appDataDir() {
  if (process.platform === 'win32') return process.env.APPDATA ?? join(homedir(), 'AppData', 'Roaming')
  if (process.platform === 'darwin') return join(homedir(), 'Library', 'Application Support')
  return process.env.XDG_CONFIG_HOME ?? join(homedir(), '.config')
}

/**
 * The development app only, so commands never touch the user's real projects by accident. The
 * installed app is used only when asked for with CLIP_APP=installed (and that app must be started
 * with CLIP_ENABLE_BRIDGE=1 to publish its connection file).
 */
function connectionCandidates() {
  if (process.env.CLIP_ENGINE_FILE) return [process.env.CLIP_ENGINE_FILE]
  const name = process.env.CLIP_APP === 'installed' ? 'Clipping App' : 'Clipping App Dev'
  return [join(appDataDir(), name, 'engine.json')]
}

async function connect() {
  if (process.env.CLIP_ENGINE_URL) return { url: process.env.CLIP_ENGINE_URL.replace(/\/$/, ''), token: process.env.CLIP_ENGINE_TOKEN ?? '' }
  for (const file of connectionCandidates()) {
    if (!existsSync(file)) continue
    try {
      const info = JSON.parse(readFileSync(file, 'utf8'))
      const res = await fetch(`${info.url}/health`, { headers: { 'x-engine-token': info.token }, signal: AbortSignal.timeout(3000) })
      if (res.ok) return { url: info.url, token: info.token, file, packaged: Boolean(info.packaged), videosDir: info.videos_dir ?? null }
    } catch {
      // Left over from an app that has closed; try the next one.
    }
  }
  throw new NotRunning(
    process.env.CLIP_APP === 'installed'
      ? 'The installed Clipping App is not running with the bridge on. Start it with CLIP_ENABLE_BRIDGE=1 set, then retry.'
      : 'The development Clipping App is not running (no live engine found). Start it with "npm run dev" from the repo root, wait for the window, then retry.'
  )
}

let conn
async function call(method, path, body) {
  conn ??= await connect()
  const res = await fetch(conn.url + path, {
    method,
    headers: { 'content-type': 'application/json', 'x-engine-token': conn.token },
    body: body === undefined ? undefined : JSON.stringify(body)
  })
  if (!res.ok) {
    let detail = res.statusText
    try {
      const data = await res.json()
      detail = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)
    } catch {
      // Not JSON: keep the status text.
    }
    throw new Error(`${method} ${path} → ${res.status}: ${detail}`)
  }
  return res.status === 204 ? null : res.json()
}

// --- waiting ------------------------------------------------------------------------------------

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
const pct = (p) => `${Math.round((p ?? 0) * 100)}%`

/** Poll until every job is in a finished state; print progress to stderr when it changes. */
async function waitFor(kind, ids, fetchOne, finished, describe) {
  const last = new Map()
  const results = new Map()
  while (results.size < ids.length) {
    for (const jobId of ids) {
      if (results.has(jobId)) continue
      const job = await fetchOne(jobId)
      const line = describe(job)
      if (last.get(jobId) !== line) {
        process.stderr.write(`${kind} ${jobId}: ${line}\n`)
        last.set(jobId, line)
      }
      if (finished(job)) results.set(jobId, job)
    }
    if (results.size < ids.length) await sleep(1000)
  }
  return ids.map((jobId) => results.get(jobId))
}

const waitSources = (ids) =>
  waitFor(
    'source',
    ids,
    (sid) => call('GET', `/sources/${sid}`),
    (s) => ['ready', 'failed', 'cancelled'].includes(s.status),
    (s) => `${s.status} ${s.status === 'ready' ? '' : pct(s.progress)}${s.error ? ` ${s.error}` : ''}`.trim()
  )

const waitAnalyses = (ids) =>
  waitFor(
    'analysis',
    ids,
    (sid) => call('GET', `/sources/${sid}/analysis`),
    (a) => ['done', 'failed', 'cancelled'].includes(a.status),
    (a) => `${a.status} ${a.stage ?? ''} ${a.status === 'done' ? `${a.clip_count ?? 0} clips` : pct(a.progress)}${a.error ? ` ${a.error}` : ''}`
  )

/** `projectOf` maps job id -> project id when known (e.g. from the POST /exports response). */
async function waitExports(ids, projectOf = new Map()) {
  // Exports are listed per project. Each project's list is fetched at most once per poll and shared
  // by all its jobs; a job of unknown project is looked up once by scanning the projects.
  const lists = new Map() // project id -> { at, jobs }
  const listFor = async (pid) => {
    const cached = lists.get(pid)
    if (cached && performance.now() - cached.at < 500) return cached.jobs
    const jobs = await call('GET', `/projects/${pid}/exports`)
    lists.set(pid, { at: performance.now(), jobs })
    return jobs
  }
  const fetchOne = async (jobId) => {
    if (!projectOf.has(jobId)) {
      for (const p of await call('GET', '/projects')) {
        for (const job of await listFor(p.id)) projectOf.set(job.id, p.id)
        if (projectOf.has(jobId)) break
      }
      if (!projectOf.has(jobId)) throw new Error(`Export ${jobId} not found`)
    }
    return (await listFor(projectOf.get(jobId))).find((j) => j.id === jobId)
  }
  return waitFor(
    'export',
    ids,
    fetchOne,
    (j) => ['done', 'failed', 'cancelled'].includes(j.status),
    (j) => `${j.status} ${j.status === 'done' ? j.output_path : pct(j.progress)}${j.error ? ` ${j.error}` : ''}`
  )
}

const anyFailed = (jobs) => jobs.some((j) => j.status !== 'ready' && j.status !== 'done')

// --- commands -----------------------------------------------------------------------------------

/** Same folder the app's export dialog suggests (main/index.ts files:default-export-dir). */
function defaultExportDir(projectName) {
  const safe = String(projectName).replace(/[<>:"/\\|?*\x00-\x1f]/g, '').trim().slice(0, 80) || 'Untitled'
  // The app publishes its real Videos folder, which can be redirected (e.g. to OneDrive).
  return join(conn?.videosDir ?? join(homedir(), 'Videos'), 'Clipping App', safe)
}

async function projectOfClip(clipId) {
  for (const p of await call('GET', '/projects')) {
    const clips = await call('GET', `/projects/${p.id}/clips`)
    if (clips.some((c) => c.id === clipId)) return p
  }
  throw new Error(`Clip ${clipId} not found`)
}

/** Short summaries keep agent context small; `api` returns the full objects. */
const sourceSummary = (s) => ({
  id: s.id,
  title: s.title,
  status: s.status,
  ...(s.status === 'ready' ? {} : { progress: s.progress }),
  duration_ms: s.duration_ms,
  size: s.width ? `${s.width}x${s.height}` : null,
  fps: s.fps,
  path: s.path,
  ...(s.url ? { url: s.url } : {}),
  ...(s.error ? { error: s.error } : {})
})

const clipSummary = (c) => ({
  id: c.id,
  source_id: c.source_id,
  title: c.title,
  start_ms: c.start_ms,
  end_ms: c.end_ms,
  status: c.status,
  ...(c.score !== null ? { score: c.score } : {}),
  formats: Object.fromEntries(Object.entries(c.formats).map(([aspect, f]) => [aspect, f.mode]))
})

const exportSummary = (j) => ({
  id: j.id,
  clip_id: j.clip_id,
  aspect: j.aspect,
  status: j.status,
  progress: j.progress,
  output_path: j.output_path,
  ...(j.encoder ? { encoder: j.encoder } : {}),
  ...(j.error ? { error: j.error } : {})
})

async function preview(video, options) {
  const ffmpeg = join(binDir, 'ffmpeg' + exe)
  const ffprobe = join(binDir, 'ffprobe' + exe)
  const tool = (path, name) => (existsSync(path) ? path : name)
  const src = resolve(need(video, 'video path'))
  if (!existsSync(src)) throw new Error(`No such file: ${src}`)
  const probe = JSON.parse(
    execFileSync(
      tool(ffprobe, 'ffprobe'),
      ['-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=avg_frame_rate:format=duration', '-of', 'json', src],
      { encoding: 'utf8' }
    )
  )
  const duration = Number(probe.format?.duration)
  if (!Number.isFinite(duration) || duration <= 0) throw new Error(`Can't tell how long ${src} is, so frames can't be picked`)
  const [num, den] = String(probe.streams?.[0]?.avg_frame_rate ?? '').split('/').map(Number)
  const frames = num > 0 && den > 0 ? Math.floor((duration * num) / den) : Infinity
  // Never ask for more frames than the video has: the sheet and the reported times would be wrong.
  const count = Math.max(1, Math.min(12, Number(options.count ?? 6), frames))
  const out = resolve(options.out ?? join(tmpdir(), `clip-preview-${Date.now()}.jpg`))
  mkdirSync(resolve(out, '..'), { recursive: true })
  // Never report a stale image from an earlier run as this one's.
  rmSync(out, { force: true })
  // Evenly spaced frames (the first, then one every `step` seconds), each 360 px tall, side by side.
  // No time stamps drawn on them: drawtext needs a fontconfig setup the Windows FFmpeg builds lack,
  // so the times are returned in the result instead.
  const step = duration / count
  execFileSync(
    tool(ffmpeg, 'ffmpeg'),
    [
      '-v', 'error', '-y', '-i', src,
      '-vf', `select='isnan(prev_selected_t)+gte(t-prev_selected_t\\,${step.toFixed(4)})',scale=-2:360,tile=${count}x1:padding=4`,
      '-fps_mode', 'vfr', '-frames:v', '1', '-q:v', '3', out
    ] // prettier-ignore
  )
  // The tile is only written once it has `count` frames, so a very short video produces nothing.
  if (!existsSync(out)) throw new Error(`No preview was made: the video has fewer than ${count} frames to sample; try a smaller --count`)
  const times = Array.from({ length: count }, (_, i) => Number((i * step).toFixed(2)))
  return { image: out, frames: count, times_s: times, duration_s: Number(duration.toFixed(3)) }
}

async function run(argv) {
  const { positional, options } = parseArgs(argv)
  const [command, ...rest] = positional

  switch (command) {
    case undefined:
    case 'help':
      process.stdout.write(HELP)
      return null

    case 'status': {
      const health = await call('GET', '/health')
      return { app: conn.packaged ? 'installed' : 'development', url: conn.url, connection_file: conn.file ?? null, version: health.version, ffmpeg_ok: health.ffmpeg.ok, hw_encoders: health.ffmpeg.hw_encoders }
    }

    case 'projects':
      return call('GET', '/projects')

    case 'project': {
      if (rest[0] === 'new') return call('POST', '/projects', { name: need(rest.slice(1).join(' '), 'project name') })
      const pid = id(rest[0], 'project id')
      const [project, sources, clips] = await Promise.all([
        call('GET', `/projects/${pid}`),
        call('GET', `/projects/${pid}/sources`),
        call('GET', `/projects/${pid}/clips`)
      ])
      return { ...project, sources: sources.map(sourceSummary), clips: clips.map(clipSummary) }
    }

    case 'import': {
      const pid = id(rest[0], 'project id')
      const inputs = rest.slice(1)
      if (inputs.length === 0) throw new UsageError('Give at least one file or link to import')
      const created = []
      for (const input of inputs) {
        const body = /^https?:\/\//i.test(input) ? { url: input } : { path: isAbsolute(input) ? input : resolve(input) }
        created.push(await call('POST', `/projects/${pid}/sources`, body))
      }
      if (!options.wait) return created.map(sourceSummary)
      const done = await waitSources(created.map((s) => s.id))
      if (anyFailed(done)) process.exitCode = 1
      return done.map(sourceSummary)
    }

    case 'sources':
      return (await call('GET', `/projects/${id(rest[0], 'project id')}/sources`)).map(sourceSummary)

    case 'analyze': {
      const sid = id(rest[0], 'source id')
      const body = {
        ...(options.mode ? { mode: options.mode } : {}),
        ...(options.count ? { clip_count: Number(options.count) } : {}),
        ...(options.min ? { min_seconds: Number(options.min) } : {}),
        ...(options.max ? { max_seconds: Number(options.max) } : {}),
        ...(options.keywords ? { keywords: list(options.keywords) } : {}),
        ...(options.model ? { model: options.model } : {})
      }
      const analysis = await call('POST', `/sources/${sid}/analyze`, body)
      if (!options.wait) return analysis
      const [done] = await waitAnalyses([sid])
      if (done.status !== 'done') process.exitCode = 1
      return { ...done, clips: (await call('GET', `/sources/${sid}/clips`)).map(clipSummary) }
    }

    case 'clips':
      return (await call('GET', `/projects/${id(rest[0], 'project id')}/clips`)).map(clipSummary)

    case 'clip': {
      const [action, ...args] = rest
      if (action === 'add') {
        const sid = id(args[0], 'source id')
        const body = { start_ms: toMs(args[1], 'start'), end_ms: toMs(args[2], 'end'), ...(options.title ? { title: String(options.title) } : {}) }
        return clipSummary(await call('POST', `/sources/${sid}/clips`, body))
      }
      if (action === 'set') {
        const body = {
          ...(options.start !== undefined ? { start_ms: toMs(options.start, 'start') } : {}),
          ...(options.end !== undefined ? { end_ms: toMs(options.end, 'end') } : {}),
          ...(options.title !== undefined ? { title: String(options.title) } : {})
        }
        if (Object.keys(body).length === 0) throw new UsageError('Nothing to change: give --start, --end or --title')
        return clipSummary(await call('PATCH', `/clips/${id(args[0], 'clip id')}`, body))
      }
      if (action === 'frame') {
        const cid = id(args[0], 'clip id')
        const aspect = need(args[1], 'aspect (e.g. 9:16)')
        const mode = need(args[2], 'mode (manual, smart or fit)')
        const body = { mode }
        if (options.crop) {
          const [x, y, w, h] = list(options.crop).map(Number)
          if ([x, y, w, h].some((v) => !Number.isFinite(v))) throw new UsageError('--crop is x,y,w,h as fractions of the frame, e.g. 0.3,0,0.4,1')
          body.crop = { x, y, w, h }
        }
        if (options.follow) body.follow = options.follow
        if (mode === 'fit') {
          body.fit = {
            background: options.background ?? 'blur',
            dim: Number(options.dim ?? 0.25),
            zoom: Number(options.zoom ?? 1),
            position: options.position ?? 'center'
          }
        }
        return clipSummary(await call('PUT', `/clips/${cid}/formats/${aspect.replace(':', 'x')}`, body))
      }
      if (action === 'rm') {
        await call('DELETE', `/clips/${id(args[0], 'clip id')}`)
        return { deleted: Number(args[0]) }
      }
      throw new UsageError(`Unknown clip action "${action ?? ''}": use add, set, frame or rm`)
    }

    case 'export': {
      const clipIds = rest.map((v) => id(v, 'clip id'))
      if (clipIds.length === 0) throw new UsageError('Give at least one clip id to export')
      const project = await projectOfClip(clipIds[0])
      const preset = {
        output_dir: resolve(options.out ?? defaultExportDir(project.name)),
        default_framing: options.framing ?? 'smart',
        captions: options.captions ?? 'off',
        quality: options.quality ?? 'high',
        resolution: Number(options.resolution ?? 1080),
        ...(options.name ? { name_template: String(options.name) } : {}),
        ...(options.fps ? { fps: String(options.fps) } : {})
      }
      const jobs = await call('POST', '/exports', { clip_ids: clipIds, aspects: list(options.aspect ?? '9:16'), preset })
      if (!options.wait) return jobs.map(exportSummary)
      const done = await waitExports(jobs.map((j) => j.id), new Map(jobs.map((j) => [j.id, j.project_id])))
      if (anyFailed(done)) process.exitCode = 1
      return done.map(exportSummary)
    }

    case 'exports':
      return (await call('GET', `/projects/${id(rest[0], 'project id')}/exports`)).map(exportSummary)

    case 'wait': {
      const [kind, ...ids] = rest
      const jobIds = ids.map((v) => id(v, `${kind} id`))
      if (jobIds.length === 0) throw new UsageError('Give the ids to wait for')
      const done =
        kind === 'source' ? (await waitSources(jobIds)).map(sourceSummary)
        : kind === 'export' ? (await waitExports(jobIds)).map(exportSummary)
        : kind === 'analysis' ? await waitAnalyses(jobIds)
        : null // prettier-ignore
      if (done === null) throw new UsageError('wait what? Use: wait source|export|analysis <id>...')
      if (done.some((j) => !['ready', 'done'].includes(j.status))) process.exitCode = 1
      return done
    }

    case 'show': {
      const body = options.source !== undefined ? { source_id: id(options.source, 'source id') } : { project_id: id(rest[0], 'project id') }
      const result = await call('POST', '/ui/show', body)
      if (result.windows === 0) process.stderr.write('Note: no app window is connected to the engine right now.\n')
      return result
    }

    case 'preview':
      return preview(rest[0], options)

    case 'api': {
      const method = String(need(rest[0], 'method')).toUpperCase()
      const path = need(rest[1], 'path')
      let body
      if (rest[2] !== undefined) {
        try {
          body = JSON.parse(rest.slice(2).join(' '))
        } catch {
          throw new UsageError('The request body must be JSON')
        }
      }
      return call(method, path.startsWith('/') ? path : `/${path}`, body)
    }

    default:
      throw new UsageError(`Unknown command "${command}". Run "node scripts/clip.mjs help".`)
  }
}

try {
  const result = await run(process.argv.slice(2))
  if (result !== null && result !== undefined) process.stdout.write(JSON.stringify(result, null, 2) + '\n')
} catch (err) {
  process.stderr.write(`Error: ${err.message}\n`)
  process.exitCode = err instanceof UsageError ? 2 : err instanceof NotRunning ? 3 : 1
}
