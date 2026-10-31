// Builds the engine into engine/dist/clipping-engine with PyInstaller, then starts it once to check it
// boots and answers /health with FFmpeg found.
import { execFileSync, spawn } from 'node:child_process'
import { existsSync, rmSync } from 'node:fs'
import { join } from 'node:path'
import { binDir, engineDir, exe, venvPython } from './paths.mjs'

const distDir = join(engineDir, 'dist', 'clipping-engine')
rmSync(join(engineDir, 'build'), { recursive: true, force: true })

console.log('> Building engine with PyInstaller (takes a few minutes)…')
execFileSync(venvPython, ['-m', 'PyInstaller', 'clipping-engine.spec', '--noconfirm', '--clean', '--log-level', 'WARN'], {
  cwd: engineDir,
  stdio: 'inherit'
})

const binary = join(distDir, `clipping-engine${exe}`)
if (!existsSync(binary)) throw new Error(`Build finished but ${binary} is missing`)

console.log('> Smoke test: starting the built engine…')
const child = spawn(binary, ['--port', '0'], {
  env: { ...process.env, CLIP_BIN_DIR: binDir, CLIP_DATA_DIR: join(engineDir, 'build', 'smoke-data'), CLIP_ENGINE_TOKEN: '' },
  stdio: ['ignore', 'pipe', 'pipe']
})
let output = ''
const port = await new Promise((resolve, reject) => {
  const timer = setTimeout(() => reject(new Error(`Engine did not start in 90s:\n${output}`)), 90_000)
  const onData = (chunk) => {
    output += chunk
    const m = /ENGINE_READY port=(\d+)/.exec(output)
    if (m) {
      clearTimeout(timer)
      resolve(m[1])
    }
  }
  child.stdout.on('data', onData)
  child.stderr.on('data', onData)
  child.on('exit', (code) => reject(new Error(`Engine exited with ${code}:\n${output}`)))
})
try {
  const health = await (await fetch(`http://127.0.0.1:${port}/health`)).json()
  if (!health.ffmpeg?.ok) throw new Error(`Engine started but FFmpeg was not found: ${JSON.stringify(health.ffmpeg)}`)
  console.log(`  ok: engine ${health.version}, schema v${health.db.schema_version}, FFmpeg ${health.ffmpeg.ffmpeg.version}`)
} finally {
  child.kill()
}
console.log(`Engine built: ${distDir}`)
