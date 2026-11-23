// Shared by setup, dev and packaging. Never use a global Python to run the engine.
import { execFileSync, spawnSync } from 'node:child_process'
import { join, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { engineDir, isWindows, venvPython } from './paths.mjs'

function usablePython(command, args = []) {
  const result = spawnSync(command, [...args, '-c', 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'], {
    stdio: 'ignore', windowsHide: true
  })
  return result.status === 0
}

function run(command, args) {
  execFileSync(command, args, { stdio: 'inherit', windowsHide: true })
}

export function ensureEngine({ dev = false } = {}) {
  if (!usablePython(venvPython)) {
    const candidates = process.env.CLIP_PYTHON
      ? [[process.env.CLIP_PYTHON, []]]
      : isWindows ? [['py', ['-3']], ['python', []], ['python3', []]] : [['python3', []], ['python', []]]
    const python = candidates.find(([command, args]) => usablePython(command, args))
    if (!python) throw new Error('Python 3.11+ was not found. Install Python, or set CLIP_PYTHON to its executable path, then retry.')
    console.log('Creating the local engine environment…')
    run(python[0], [...python[1], '-m', 'venv', join(engineDir, '.venv')])
  }

  const requirements = join(engineDir, dev ? 'requirements-dev.txt' : 'requirements.txt')
  const check = () => spawnSync(venvPython, [join(engineDir, 'check_dependencies.py'), requirements], {
    encoding: 'utf8', windowsHide: true
  })
  let result = check()
  if (result.status !== 0) {
    console.log(`Updating engine dependencies for this device…\n${result.stdout || result.stderr || ''}`)
    try {
      run(venvPython, ['-m', 'pip', 'install', '-r', requirements])
    } catch {
      throw new Error('Engine dependency installation failed. Check the pip output above and your network connection, then retry "npm run setup".')
    }
    result = check()
    if (result.status !== 0) throw new Error(`Engine dependencies are still incomplete:\n${result.stdout || result.stderr}`)
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  ensureEngine({ dev: process.argv.includes('--dev') })
}
