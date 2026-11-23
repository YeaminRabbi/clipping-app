// Copies ffmpeg and ffprobe into bin/ so the app ships its own copy instead of relying on PATH.
// Usage:
//   npm run bundle:ffmpeg                  copy from the FFmpeg found on PATH
//   npm run bundle:ffmpeg -- <folder>      copy from a folder containing ffmpeg/ffprobe
import { execFileSync } from 'node:child_process'
import { copyFileSync, existsSync, mkdirSync, realpathSync, rmSync } from 'node:fs'
import { dirname, join } from 'node:path'
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
// Texts from an earlier build must not be taken for this one's.
for (const name of ['FFMPEG-LICENSE.txt', 'FFMPEG-README.txt']) rmSync(join(binDir, name), { force: true })

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

// The license and the list of sources come with the download, in the folder above bin/. The installer
// must carry them (scripts/collect-licenses.mjs), so keep them with the binaries.
const ffmpegPath = fromDir ? join(fromDir, 'ffmpeg' + exe) : findOnPath('ffmpeg').trim()
const folder = dirname(realpathSync(ffmpegPath))
for (const [names, dest] of [
  [['LICENSE', 'LICENSE.txt'], 'FFMPEG-LICENSE.txt'],
  [['README.txt', 'README'], 'FFMPEG-README.txt']
]) {
  const found = [dirname(folder), folder].flatMap((d) => names.map((n) => join(d, n))).find((p) => existsSync(p))
  if (found) copyFileSync(found, join(binDir, dest))
  else console.warn(`No ${names[0]} found next to this FFmpeg. Fine for development; "npm run dist" needs a build that includes it.`)
}
