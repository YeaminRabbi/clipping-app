import { spawn, type ChildProcess } from 'node:child_process'
import { randomBytes } from 'node:crypto'
import { existsSync, mkdirSync } from 'node:fs'
import { join, parse, resolve } from 'node:path'
import { app } from 'electron'
import { log, logsDir } from './log'
import type { EngineStatus } from '../shared/types'

// Generous: the first launch of the packaged engine can be slow while antivirus scans it.
const STARTUP_TIMEOUT_MS = 60_000
const MAX_LOG_LINES = 200
const READY_PATTERN = /ENGINE_READY port=(\d+)/

interface EngineCommand {
  command: string
  args: string[]
  cwd: string
  binDir: string
}

/** Where the engine lives: the dev venv in the repo, or the PyInstaller build inside the app resources. */
function resolveEngineCommand(): EngineCommand {
  const configuredBinDir = process.env.CLIPPING_APP_FFMPEG_DIR?.trim() || process.env.CLIP_BIN_DIR?.trim()
  if (app.isPackaged) {
    const engineDir = join(process.resourcesPath, 'engine')
    const exe = process.platform === 'win32' ? 'clipping-engine.exe' : 'clipping-engine'
    return {
      command: join(engineDir, exe),
      args: ['--port', '0'],
      cwd: engineDir,
      binDir: configuredBinDir ? resolve(configuredBinDir) : join(process.resourcesPath, 'bin')
    }
  }
  const repoRoot = resolve(app.getAppPath(), '..', '..')
  const engineDir = join(repoRoot, 'engine')
  const python =
    process.platform === 'win32'
      ? join(engineDir, '.venv', 'Scripts', 'python.exe')
      : join(engineDir, '.venv', 'bin', 'python')
  const sharedBinDir =
    process.platform === 'win32' ? join(parse(repoRoot).root, 'Dev Tools', 'FFmpeg') : join(repoRoot, 'bin')
  const sharedToolsExist = ['ffmpeg', 'ffprobe'].every((name) =>
    existsSync(join(sharedBinDir, `${name}${process.platform === 'win32' ? '.exe' : ''}`))
  )
  const binDir = configuredBinDir
    ? resolve(configuredBinDir)
    : sharedToolsExist
      ? sharedBinDir
      : join(repoRoot, 'bin')
  return { command: python, args: ['run.py', '--port', '0'], cwd: engineDir, binDir }
}

export class EngineProcess {
  private child: ChildProcess | null = null
  private status: EngineStatus = { state: 'stopped', url: null, token: null, error: null, logs: [] }
  private listeners = new Set<(status: EngineStatus) => void>()

  getStatus(): EngineStatus {
    return { ...this.status, logs: [...this.status.logs] }
  }

  onStatus(listener: (status: EngineStatus) => void): () => void {
    this.listeners.add(listener)
    return () => this.listeners.delete(listener)
  }

  private update(patch: Partial<EngineStatus>): void {
    this.status = { ...this.status, ...patch }
    const snapshot = this.getStatus()
    for (const listener of this.listeners) listener(snapshot)
  }

  private log(chunk: string): void {
    const lines = chunk.split(/\r?\n/).filter(Boolean)
    if (lines.length === 0) return
    this.status.logs = [...this.status.logs, ...lines].slice(-MAX_LOG_LINES)
  }

  start(): Promise<EngineStatus> {
    if (this.child) return Promise.resolve(this.getStatus())

    const { command, args, cwd, binDir } = resolveEngineCommand()
    if (!existsSync(command)) {
      const error = app.isPackaged
        ? `Engine executable missing: ${command}`
        : `Python venv not found at ${command}. Run "npm run setup" in the project root.`
      this.update({ state: 'error', error, url: null, token: null })
      log('error', error)
      return Promise.resolve(this.getStatus())
    }

    const dataDir = join(app.getPath('userData'), 'data')
    const tempDir = app.getPath('temp')
    mkdirSync(dataDir, { recursive: true })
    const token = randomBytes(32).toString('hex')

    this.update({ state: 'starting', url: null, token: null, error: null, logs: [] })

    const child = spawn(command, args, {
      cwd,
      env: {
        ...process.env,
        CLIP_DATA_DIR: dataDir,
        CLIP_BIN_DIR: binDir,
        CLIP_ENGINE_TOKEN: token,
        CLIP_LOG_DIR: logsDir(),
        CLIP_TEMP_DIR: tempDir,
        TEMP: tempDir,
        TMP: tempDir,
        TMPDIR: tempDir,
        HF_HOME: join(dataDir, 'cache', 'huggingface'),
        XDG_CACHE_HOME: join(dataDir, 'cache'),
        PYTHONUNBUFFERED: '1'
      },
      windowsHide: true
    })
    this.child = child
    log('info', `Starting engine: ${command} ${args.join(' ')}`)

    return new Promise((resolvePromise) => {
      let settled = false
      const settle = (): void => {
        if (settled) return
        settled = true
        clearTimeout(timer)
        resolvePromise(this.getStatus())
      }

      const timer = setTimeout(() => {
        this.update({ state: 'error', error: `Engine did not start within ${STARTUP_TIMEOUT_MS / 1000}s` })
        log('error', `Engine start timed out. Last output:\n${this.status.logs.slice(-20).join('\n')}`)
        this.stop()
        settle()
      }, STARTUP_TIMEOUT_MS)

      child.stdout?.setEncoding('utf8')
      child.stdout?.on('data', (chunk: string) => {
        this.log(chunk)
        const match = READY_PATTERN.exec(chunk)
        if (match && this.status.state === 'starting') {
          this.update({ state: 'ready', url: `http://127.0.0.1:${match[1]}`, token })
          log('info', `Engine ready on port ${match[1]}`)
          settle()
        }
      })
      child.stderr?.setEncoding('utf8')
      child.stderr?.on('data', (chunk: string) => this.log(chunk))

      child.on('error', (err) => {
        this.child = null
        this.update({ state: 'error', error: `Failed to launch engine: ${err.message}`, url: null, token: null })
        log('error', `Failed to launch engine: ${err.message}`)
        settle()
      })
      child.on('exit', (code, signal) => {
        if (this.child !== child) return
        this.child = null
        if (this.status.state !== 'stopped') {
          const tail = this.status.logs.slice(-5).join('\n')
          log('error', `Engine exited unexpectedly (${signal ?? `code ${code}`}). Last output:\n${this.status.logs.slice(-30).join('\n')}`)
          this.update({
            state: 'error',
            url: null,
            token: null,
            error: `Engine exited (${signal ?? `code ${code}`})${tail ? `:\n${tail}` : ''}`
          })
        }
        settle()
      })
    })
  }

  stop(): void {
    const child = this.child
    this.child = null
    this.update({ state: 'stopped', url: null, token: null })
    if (child && child.exitCode === null) child.kill()
  }

  async restart(): Promise<EngineStatus> {
    this.stop()
    return this.start()
  }
}
