/** What the updater may do on its own. Kept free of Electron so it can be tested. */
export interface UpdatePolicy {
  /** Whether the updater checks who signed a downloaded installer before running it. */
  verified: boolean
  autoDownload: boolean
  autoInstallOnAppQuit: boolean
}

/**
 * electron-builder writes `publisherName` into app-update.yml only for signed builds, and
 * electron-updater checks an update's signature only when it's there. Without it, the only check is
 * a hash that comes from the same place as the installer, so whoever can publish a release could run
 * code on every user's PC. Such builds never download or install anything the user didn't ask for.
 */
export function updatePolicy(appUpdateYml: string | null): UpdatePolicy {
  const lines = (appUpdateYml ?? '').split(/\r?\n/)
  const at = lines.findIndex((line) => /^publisherName:/.test(line))
  const inline = at < 0 ? '' : lines[at].slice('publisherName:'.length).trim()
  const listed = at >= 0 && /^\s*-\s*\S/.test(lines[at + 1] ?? '')
  const verified = listed || !['', '[]', 'null', '~', '""', "''"].includes(inline)
  return { verified, autoDownload: verified, autoInstallOnAppQuit: verified }
}
