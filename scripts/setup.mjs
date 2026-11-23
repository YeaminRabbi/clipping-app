// One-time developer setup: creates the engine's Python venv, installs its dependencies,
// and downloads the Electron binary.
import { execFileSync } from 'node:child_process'
import { join } from 'node:path'
import { root } from './paths.mjs'
import { ensureEngine } from './ensure-engine.mjs'

const run = (cmd, args, opts = {}) => {
  console.log(`> ${cmd} ${args.join(' ')}`)
  execFileSync(cmd, args, { stdio: 'inherit', ...opts })
}

ensureEngine({ dev: true })

// Electron 45+ fetches its binary on demand rather than in a postinstall script.
run(process.execPath, [join(root, 'node_modules', 'electron', 'install.js')])

console.log('\nSetup complete. Next: "npm run bundle:ffmpeg", then "npm run dev".')
