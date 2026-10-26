import { spawnSync } from 'node:child_process'
import { engineDir, venvPython } from './paths.mjs'

const result = spawnSync(venvPython, ['-m', 'pytest', '-q', ...process.argv.slice(2)], {
  cwd: engineDir,
  stdio: 'inherit'
})
process.exit(result.status ?? 1)
