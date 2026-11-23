// Collects the license texts the installer must carry into apps/desktop/licenses-out (not committed):
// FFmpeg (GPL) with where its source is, every Python package in the engine, the npm packages in the
// app, and the bundled face detector. Run by `npm run dist`; it fails rather than ship without them.
import { execFileSync } from 'node:child_process'
import { cpSync, existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { binDir, engineDir, exe, root, venvPython } from './paths.mjs'

// npm packages whose code ends up in the app. Electron's own licenses are added by electron-builder.
const NPM_PACKAGES = ['react', 'react-dom', 'scheduler', 'zustand', 'lucide-react', 'electron-updater']
// Not part of the packaged engine.
const BUILD_ONLY = new Set(['pip', 'setuptools', 'pytest', 'pluggy', 'iniconfig', 'pyinstaller', 'pyinstaller-hooks-contrib', 'altgraph', 'pefile', 'pywin32-ctypes'])

const PYTHON_LIST = `
import importlib.metadata as m, json
out = []
for d in m.distributions():
    files = [str(d.locate_file(f)) for f in d.files or [] if f.suffix != '.py' and any(k in f.name.lower() for k in ('licen', 'copying', 'notice'))]
    meta = d.metadata
    out.append({'name': d.name, 'version': d.version, 'license': meta.get('License-Expression') or (meta.get('License') or '').split('\\n')[0][:80] or ', '.join(c.split('::')[-1].strip() for c in meta.get_all('Classifier') or [] if 'License' in c),
                'home': meta.get('Home-page') or next((u.split(',', 1)[1].strip() for u in meta.get_all('Project-URL') or []), ''), 'files': files})
print(json.dumps(out))
`

/** What the FFmpeg build in bin/ says about itself, or an error if its license text isn't next to it. */
export function ffmpegNotice(bin, describe) {
  const license = join(bin, 'FFMPEG-LICENSE.txt')
  if (!existsSync(license)) {
    throw new Error(`${license} is missing. Run "npm run bundle:ffmpeg -- <folder>" with the folder of an FFmpeg download that includes its LICENSE file.`)
  }
  const { version, configuration } = describe()
  const gpl = configuration.includes('--enable-gpl')
  if (configuration.includes('--enable-nonfree')) throw new Error('This FFmpeg build is "nonfree" and may not be distributed. Use another one.')
  return [
    `FFmpeg ${version} (ffmpeg${exe}, ffprobe${exe}), a separate program this app runs.`,
    `License: GNU ${gpl ? 'General' : 'Lesser General'} Public License; full text in FFMPEG-LICENSE.txt${gpl ? ' and GPL-3.0.txt' : ''}.`,
    'Source code: FFMPEG-README.txt names the exact FFmpeg commit and the versions of the libraries in it.',
    'The same sources are attached to the release you got this app from, or ask the publisher for them.',
    `Build configuration: ${configuration}`
  ].join('\n')
}

function describeFfmpeg() {
  const out = execFileSync(join(binDir, `ffmpeg${exe}`), ['-hide_banner', '-version'], { encoding: 'utf8' })
  return { version: /version\s+(\S+)/.exec(out)?.[1] ?? 'unknown', configuration: /configuration:\s*(.*)/.exec(out)?.[1]?.trim() ?? '' }
}

function npmPackages() {
  return NPM_PACKAGES.map((name) => {
    const dir = join(root, 'node_modules', name)
    const meta = JSON.parse(readFileSync(join(dir, 'package.json'), 'utf8'))
    const files = readdirSync(dir).filter((f) => /^(licen[sc]e|copying|notice)/i.test(f)).map((f) => join(dir, f))
    return { name, version: meta.version, license: meta.license ?? '', home: meta.homepage ?? '', files }
  })
}

export function notices(title, packages) {
  const parts = [`==== ${title} ====`]
  for (const p of [...packages].sort((a, b) => a.name.localeCompare(b.name))) {
    parts.push(`\n---- ${p.name} ${p.version} (${p.license || 'license not stated'}) ${p.home}`)
    const texts = [...new Set(p.files.filter((f) => existsSync(f)).map((f) => readFileSync(f, 'utf8').trim()))]
    parts.push(texts.length ? texts.join('\n\n') : 'The package contains no license file; see its home page.')
  }
  return parts.join('\n')
}

export function collectLicenses(out = join(root, 'apps', 'desktop', 'licenses-out')) {
  const ffmpeg = ffmpegNotice(binDir, describeFfmpeg)
  const python = JSON.parse(execFileSync(venvPython, ['-c', PYTHON_LIST], { encoding: 'utf8', cwd: engineDir, maxBuffer: 64 * 1024 * 1024 }))
  rmSync(out, { recursive: true, force: true })
  mkdirSync(out, { recursive: true })
  cpSync(join(root, 'licenses'), out, { recursive: true })
  for (const name of ['FFMPEG-LICENSE.txt', 'FFMPEG-README.txt']) {
    if (existsSync(join(binDir, name))) cpSync(join(binDir, name), join(out, name))
  }
  writeFileSync(
    join(out, 'THIRD-PARTY-NOTICES.txt'),
    [
      'Clipping App includes the following third-party software.',
      `\n==== FFmpeg ====\n${ffmpeg}`,
      '\n==== Other media libraries ====',
      'PyAV contains FFmpeg libraries (LGPL-3.0, see LGPL-3.0.txt) together with libx264 and libx265 (GPL-2.0 or later, see GPL-3.0.txt).',
      'OpenCV contains FFmpeg libraries (LGPL); see its notices below.',
      '\n==== YuNet face detection model ====\nMIT, see yunet-MIT.txt. https://github.com/opencv/opencv_zoo',
      `\n${notices('Python packages', python.filter((p) => !BUILD_ONLY.has(p.name.toLowerCase())))}`,
      `\n${notices('JavaScript packages', npmPackages())}`
    ].join('\n') + '\n'
  )
  return out
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  console.log(`Licenses collected: ${collectLicenses()}`)
}
