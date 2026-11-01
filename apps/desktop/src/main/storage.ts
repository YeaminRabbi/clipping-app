import { mkdirSync } from 'node:fs'
import { join, parse, resolve } from 'node:path'
import { app } from 'electron'

export const DATA_ROOT_ENV = 'CLIPPING_APP_DATA_ROOT'

/**
 * Configure every Electron-owned writable directory before the app becomes ready.
 *
 * Installed builds retain Electron's platform defaults unless CLIPPING_APP_DATA_ROOT is set.
 * Development defaults to "<project drive>:\\Dev Tools\\Clipping App Dev", which keeps a
 * checkout on a secondary drive self-contained without baking a particular drive letter into
 * the application. Any computer can override the location with CLIPPING_APP_DATA_ROOT.
 */
export function configureStoragePaths(): string {
  const configured = process.env[DATA_ROOT_ENV]?.trim()
  const projectRoot = resolve(app.getAppPath(), '..', '..')
  const developmentDefault =
    process.platform === 'win32'
      ? join(parse(projectRoot).root, 'Dev Tools', 'Clipping App Dev')
      : join(app.getPath('appData'), 'Clipping App Dev')
  const root = resolve(configured || (app.isPackaged ? app.getPath('userData') : developmentDefault))

  const temp = join(root, 'temp')
  const localCache = join(root, 'cache', 'local-app-data')
  for (const path of [root, join(root, 'logs'), join(root, 'crash-dumps'), temp, localCache]) {
    mkdirSync(path, { recursive: true })
  }

  // sessionData owns Chromium storage and caches. Keeping it under the same root also preserves
  // existing development profiles copied from Electron's former userData directory.
  app.setPath('userData', root)
  app.setPath('sessionData', root)
  app.setPath('logs', join(root, 'logs'))
  app.setPath('crashDumps', join(root, 'crash-dumps'))
  app.setPath('temp', temp)

  // Native modules and the Python engine may consult the process environment directly.
  process.env.TEMP = temp
  process.env.TMP = temp
  process.env.TMPDIR = temp
  // electron-updater derives its download cache from LOCALAPPDATA. This is process-local and does
  // not alter the user's system environment or the APPDATA setting inherited by other programs.
  if (process.platform === 'win32') process.env.LOCALAPPDATA = localCache
  process.env[DATA_ROOT_ENV] = root
  return root
}
