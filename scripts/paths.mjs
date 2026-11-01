import { join, resolve, dirname, parse } from 'node:path'
import { fileURLToPath } from 'node:url'

export const root = resolve(dirname(fileURLToPath(import.meta.url)), '..')
export const engineDir = join(root, 'engine')
export const binDir = join(root, 'bin')
export const isWindows = process.platform === 'win32'
export const exe = isWindows ? '.exe' : ''
export const devToolsDir = resolve(
  process.env.CLIPPING_DEV_TOOLS_ROOT || (isWindows ? join(parse(root).root, 'Dev Tools') : join(root, '.dev-tools'))
)
export const sharedFfmpegDir = resolve(process.env.CLIPPING_APP_FFMPEG_DIR || join(devToolsDir, 'FFmpeg'))
export const sharedPython = resolve(process.env.CLIPPING_APP_PYTHON || join(devToolsDir, 'Python312', `python${exe}`))
export const tempDir = join(devToolsDir, 'Temp')
export const venvPython = isWindows
  ? join(engineDir, '.venv', 'Scripts', 'python.exe')
  : join(engineDir, '.venv', 'bin', 'python')
