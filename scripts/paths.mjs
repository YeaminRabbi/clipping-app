import { join, resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

export const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
export const engineDir = join(root, 'engine')
export const binDir = join(root, 'bin')
export const isWindows = process.platform === 'win32'
export const exe = isWindows ? '.exe' : ''
export const venvPython = isWindows
  ? join(engineDir, '.venv', 'Scripts', 'python.exe')
  : join(engineDir, '.venv', 'bin', 'python')
