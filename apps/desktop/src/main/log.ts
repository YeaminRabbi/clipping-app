import { appendFileSync, mkdirSync, renameSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { app } from 'electron'

const MAX_BYTES = 2 * 1024 * 1024

let logFile: string | null = null

export function logsDir(): string {
  return app.getPath('logs')
}

function file(): string {
  if (!logFile) {
    mkdirSync(logsDir(), { recursive: true })
    logFile = join(logsDir(), 'main.log')
  }
  return logFile
}

/** Append a line to main.log, keeping one previous file when it grows past 2 MB. */
export function log(level: 'info' | 'warn' | 'error', message: string): void {
  const line = `${new Date().toISOString()} ${level.toUpperCase()} ${message}\n`
  try {
    const path = file()
    try {
      if (statSync(path).size > MAX_BYTES) renameSync(path, `${path}.1`)
    } catch {
      // No log file yet.
    }
    appendFileSync(path, line)
  } catch {
    // Logging must never take the app down.
  }
  if (level === 'error') console.error(line.trimEnd())
}
