// One-time developer setup: creates the engine's Python venv, installs its dependencies,
// and downloads the Electron binary.
import { execFileSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { join } from 'node:path'
import { engineDir, root, venvPython, isWindows } from './paths.mjs'

const run = (cmd, args, opts = {}) => {
  console.log(`> ${cmd} ${args.join(' ')}`)
  execFileSync(cmd, args, { stdio: 'inherit', ...opts })
}

if (!existsSync(venvPython)) {
  run(isWindows ? 'python' : 'python3', ['-m', 'venv', join(engineDir, '.venv')])
}
run(venvPython, ['-m', 'pip', 'install', '--upgrade', 'pip'])
run(venvPython, ['-m', 'pip', 'install', '-r', join(engineDir, 'requirements-dev.txt')])

// Electron 45+ fetches its binary on demand rather than in a postinstall script.
run(process.execPath, [join(root, 'node_modules', 'electron', 'install.js')])

console.log('\nSetup complete. Next: "npm run bundle:ffmpeg", then "npm run dev".')
