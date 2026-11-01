// Run desktop tooling with caches and temporary files on the development-tools drive.
import { execFileSync } from 'node:child_process'
import { existsSync, mkdirSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { devToolsDir, tempDir } from './paths.mjs'

const script = process.argv[2]
if (!script) throw new Error('Usage: node scripts/run-desktop.mjs <workspace-script>')

for (const path of [tempDir, join(devToolsDir, 'npm-cache'), join(devToolsDir, 'Electron', 'Cache')]) {
  mkdirSync(path, { recursive: true })
}

process.env.TEMP = tempDir
process.env.TMP = tempDir
process.env.TMPDIR = tempDir
process.env.npm_config_cache ??= join(devToolsDir, 'npm-cache')
process.env.electron_config_cache ??= join(devToolsDir, 'Electron', 'Cache')
process.env.ELECTRON_BUILDER_CACHE ??= join(devToolsDir, 'electron-builder-cache')
// Some automation hosts set this for their own Electron subprocesses. It must not leak into the app.
delete process.env.ELECTRON_RUN_AS_NODE

const npmCliFromCurrentNode = join(dirname(process.execPath), 'node_modules', 'npm', 'bin', 'npm-cli.js')
const npmCli = existsSync(npmCliFromCurrentNode) ? npmCliFromCurrentNode : process.env.npm_execpath
if (!npmCli) throw new Error('Could not locate npm-cli.js')
execFileSync(process.execPath, [npmCli, '--workspace', 'apps/desktop', 'run', script], {
  cwd: new URL('..', import.meta.url),
  env: process.env,
  stdio: 'inherit'
})
