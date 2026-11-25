/**
 * Where exports go by default. Settings can pick a base folder; each project then exports into
 * <base>/<project name>. Without one, the app's own default (Videos/Clipping App/<project>) is used.
 */
const EXPORT_BASE_KEY = 'clipping.exportBase'
const PRESET_STORAGE_KEY = 'clipping.exportPreset'

export function getExportBase(): string | null {
  try {
    return localStorage.getItem(EXPORT_BASE_KEY) || null
  } catch {
    return null
  }
}

/** Saves (or clears) the base folder, and forgets the last-used export folder so the new one applies. */
export function setExportBase(dir: string | null): void {
  try {
    if (dir) localStorage.setItem(EXPORT_BASE_KEY, dir)
    else localStorage.removeItem(EXPORT_BASE_KEY)
    const raw = localStorage.getItem(PRESET_STORAGE_KEY)
    if (raw) {
      const preset = JSON.parse(raw) as Record<string, unknown>
      delete preset.output_dir
      localStorage.setItem(PRESET_STORAGE_KEY, JSON.stringify(preset))
    }
  } catch {
    // Remembering the folder is a convenience only.
  }
}

/** Same clean-up the main process applies to project names used as folder names. */
function safeFolderName(name: string): string {
  return name.replace(/[<>:"/\\|?*\x00-\x1f]/g, '').trim().slice(0, 80) || 'Untitled'
}

/** The default export folder for a project. */
export async function exportDirFor(projectName: string): Promise<string> {
  const base = getExportBase()
  if (!base) return window.clipping.files.defaultExportDir(projectName)
  const sep = base.includes('\\') ? '\\' : '/'
  return `${base.replace(/[\\/]+$/, '')}${sep}${safeFolderName(projectName)}`
}

/** The base folder Settings shows: the chosen one, or the parent of the app's default. */
export async function displayedExportBase(): Promise<string> {
  const base = getExportBase()
  if (base) return base
  const sample = await window.clipping.files.defaultExportDir('x')
  return sample.replace(/[\\/][^\\/]*$/, '')
}
