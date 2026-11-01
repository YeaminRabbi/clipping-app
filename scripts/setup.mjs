// One-time developer setup: creates the engine's Python venv, installs its dependencies,
// and downloads the Electron binary.
import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync } from 'node:fs'
import { join } from 'node:path'
import { engineDir, root, venvPython, isWindows, devToolsDir, tempDir, sharedPython } from './paths.mjs'

mkdirSync(tempDir, { recursive: true })
process.env.PIP_CACHE_DIR ??= join(devToolsDir, 'pip-cache')
process.env.electron_config_cache ??= join(devToolsDir, 'Electron', 'Cache')
process.env.ELECTRON_BUILDER_CACHE ??= join(devToolsDir, 'electron-builder-cache')
process.env.TEMP = tempDir
process.env.TMP = tempDir

const run = (cmd, args, opts = {}) => {
  console.log(`> ${cmd} ${args.join(' ')}`)
  execFileSync(cmd, args, { stdio: 'inherit', ...opts })
}

if (!existsSync(venvPython)) {
  const bootstrapPython = existsSync(sharedPython) ? sharedPython : isWindows ? 'python' : 'python3'
  run(bootstrapPython, ['-m', 'venv', join(engineDir, '.venv')])
}
run(venvPython, ['-m', 'pip', 'install', '--upgrade', 'pip'])
run(venvPython, ['-m', 'pip', 'install', '-r', join(engineDir, 'requirements-dev.txt')])

// Electron 45+ fetches its binary on demand rather than in a postinstall script.
run(process.execPath, [join(root, 'node_modules', 'electron', 'install.js')])

console.log('\nSetup complete. Next: "npm run bundle:ffmpeg", then "npm run dev".')
