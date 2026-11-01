import { spawnSync } from 'node:child_process'
import { mkdirSync } from 'node:fs'
import { engineDir, venvPython, tempDir } from './paths.mjs'

mkdirSync(tempDir, { recursive: true })
process.env.TEMP = tempDir
process.env.TMP = tempDir
process.env.TMPDIR = tempDir

const result = spawnSync(venvPython, ['-m', 'pytest', '-q', ...process.argv.slice(2)], {
  cwd: engineDir,
  stdio: 'inherit'
})
process.exit(result.status ?? 1)
