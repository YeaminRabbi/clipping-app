// Copies ffmpeg and ffprobe into bin/ so the app ships its own copy instead of relying on PATH.
// Usage:
//   npm run bundle:ffmpeg                  copy from the FFmpeg found on PATH
//   npm run bundle:ffmpeg -- <folder>      copy from a folder containing ffmpeg/ffprobe
import { execFileSync } from 'node:child_process'
import { copyFileSync, existsSync, mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { binDir, exe, isWindows } from './paths.mjs'

function findOnPath(name) {
  try {
    const out = execFileSync(isWindows ? 'where' : 'which', [name], { encoding: 'utf8' })
    return out.split(/\r?\n/).find((line) => line.trim().endsWith(name + exe)) ?? null
  } catch {
    return null
  }
}

const fromDir = process.argv[2]
mkdirSync(binDir, { recursive: true })

for (const name of ['ffmpeg', 'ffprobe']) {
  const src = fromDir ? join(fromDir, name + exe) : findOnPath(name)
  if (!src || !existsSync(src)) {
    console.error(
      `Could not find ${name}${exe}${fromDir ? ` in ${fromDir}` : ' on PATH'}.\n` +
        'Install FFmpeg (e.g. "winget install Gyan.FFmpeg") or pass the folder that contains it.'
    )
    process.exit(1)
  }
  const dest = join(binDir, name + exe)
  copyFileSync(src.trim(), dest)
  const version = execFileSync(dest, ['-version'], { encoding: 'utf8' }).split(/\r?\n/)[0]
  console.log(`${name}: ${src.trim()} -> ${dest}\n  ${version}`)
}
