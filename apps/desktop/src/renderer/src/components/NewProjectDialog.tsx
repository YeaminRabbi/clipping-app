import { Check, Film, LoaderCircle, Upload, X } from 'lucide-react'
import { useState, type DragEvent } from 'react'
import { useApp } from '../store'
import { Modal } from './Modal'
import { describePrefs, loadPrefs, paramsFromPrefs } from '../lib/autoClipPrefs'

const AUTO_KEY = 'clipping.autoClipNewProjects'

const fileName = (path: string): string => path.split(/[\\/]/).pop() ?? path

/** "ranked-night_2026-11-20.mkv" -> "ranked night 2026-11-20" */
function nameFromFile(path: string): string {
  const base = fileName(path).replace(/\.[^.]+$/, '')
  const spaced = base.replace(/[_]+/g, ' ').replace(/\s+/g, ' ').trim()
  return (spaced || 'New project').slice(0, 80)
}

function loadAutoChoice(): boolean {
  try {
    return localStorage.getItem(AUTO_KEY) !== 'false'
  } catch {
    return true
  }
}

/**
 * New project in one step: pick (or drop) the videos, name it (filled in from the first file),
 * choose whether to find clips as soon as the import finishes, then Create opens the project with
 * the videos importing.
 */
export function NewProjectDialog({ initialPaths, onClose }: { initialPaths: string[]; onClose(): void }) {
  const { createProject, openProject, addFiles, setAutoClipOnReady } = useApp.getState()
  const [paths, setPaths] = useState<string[]>(initialPaths)
  const [name, setName] = useState(initialPaths.length ? nameFromFile(initialPaths[0]) : '')
  const [nameTouched, setNameTouched] = useState(false)
  const [autoClip, setAutoClip] = useState(loadAutoChoice)
  const [dragging, setDragging] = useState(false)
  const [busy, setBusy] = useState(false)
  const prefs = loadPrefs()

  const addPaths = (more: string[]) => {
    if (!more.length) return
    const next = [...paths, ...more.filter((p) => !paths.includes(p))]
    setPaths(next)
    if (!nameTouched && !name.trim()) setName(nameFromFile(next[0]))
  }

  const browse = async () => addPaths(await window.clipping.files.pickVideos())

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    e.stopPropagation()
    setDragging(false)
    addPaths([...e.dataTransfer.files].map((f) => window.clipping.files.pathFor(f)).filter(Boolean))
  }

  const remove = (path: string) => setPaths(paths.filter((p) => p !== path))

  const create = async () => {
    const projectName = name.trim()
    if (!projectName || paths.length === 0 || busy) return
    setBusy(true)
    try {
      localStorage.setItem(AUTO_KEY, String(autoClip))
    } catch {
      // Remembering the choice is a convenience only.
    }
    const project = await createProject(projectName)
    if (!project) {
      setBusy(false)
      return
    }
    await openProject(project.id)
    onClose()
    const added = await addFiles(paths)
    if (autoClip) {
      const params = paramsFromPrefs(prefs)
      for (const source of added) setAutoClipOnReady(source.id, params)
    }
  }

  return (
    <Modal
      title="New project"
      size="sm"
      onClose={onClose}
      footer={
        <>
          <span />
          <div className="flex gap-2">
            <button onClick={onClose} className="rounded-md border border-control px-4 py-2 text-sm hover:bg-white/10">
              Cancel
            </button>
            <button
              onClick={() => void create()}
              disabled={busy || paths.length === 0 || !name.trim()}
              title={paths.length === 0 ? 'Add a video first' : undefined}
              className="inline-flex items-center gap-2 rounded-md bg-accent px-4 py-2 text-sm font-semibold text-on-accent hover:bg-accent-hover disabled:opacity-40"
            >
              {busy && <LoaderCircle size={15} className="animate-spin" aria-hidden />}
              Create project
            </button>
          </div>
        </>
      }
    >
      <div className="flex flex-col gap-4 overflow-auto px-5 py-5">
        <div
          onDragOver={(e) => {
            e.preventDefault()
            e.stopPropagation()
            setDragging(true)
          }}
          onDragLeave={(e) => {
            if (!e.currentTarget.contains(e.relatedTarget as Node)) setDragging(false)
          }}
          onDrop={onDrop}
        >
          {paths.length === 0 ? (
            <button
              onClick={() => void browse()}
              data-autofocus
              className={`not-pill flex h-40 w-full flex-col items-center justify-center gap-2 rounded-2xl border border-dashed text-sm transition-colors ${
                dragging ? 'border-white/60 bg-white/10' : 'border-[rgba(160,180,220,0.45)] bg-white/[0.03] hover:bg-white/[0.06]'
              }`}
            >
              <span className="grid size-11 place-items-center rounded-full bg-accent text-on-accent">
                <Upload size={19} strokeWidth={1.8} aria-hidden />
              </span>
              <span className="font-semibold">Drop a video here or choose a file</span>
              <span className="text-xs text-muted">You can add more videos to the project later</span>
            </button>
          ) : (
            <div className={`flex flex-col gap-1.5 rounded-2xl border border-dashed p-2 ${dragging ? 'border-white/60 bg-white/10' : 'border-[rgba(160,180,220,0.35)]'}`}>
              {paths.map((path) => (
                <div key={path} className="flex items-center gap-3 rounded-xl px-2 py-1.5">
                  <Film size={18} strokeWidth={1.6} className="shrink-0 text-muted" aria-hidden />
                  <span className="min-w-0 flex-1 truncate text-sm" title={path}>
                    {fileName(path)}
                  </span>
                  <button
                    onClick={() => remove(path)}
                    aria-label={`Remove ${fileName(path)}`}
                    className="not-pill grid size-7 place-items-center rounded-full text-muted hover:bg-white/10 hover:text-ink"
                  >
                    <X size={14} aria-hidden />
                  </button>
                </div>
              ))}
              <button onClick={() => void browse()} className="self-start rounded-md px-2 py-1 text-xs text-muted hover:bg-white/10 hover:text-ink">
                + Add another video
              </button>
            </div>
          )}
        </div>

        <label className="flex flex-col gap-1.5 text-xs text-muted">
          Project name
          <input
            value={name}
            onChange={(e) => {
              setName(e.target.value)
              setNameTouched(true)
            }}
            onKeyDown={(e) => e.key === 'Enter' && void create()}
            placeholder="Filled in from the video's name"
            maxLength={120}
            className="h-11 rounded-full border border-white/15 bg-[rgba(6,12,26,0.45)] px-4 text-sm text-ink outline-none placeholder:text-[#8794b0] focus:border-white/40"
          />
        </label>

        <button
          role="checkbox"
          aria-checked={autoClip}
          onClick={() => setAutoClip(!autoClip)}
          className="not-pill flex items-start gap-3 rounded-2xl border border-line bg-white/[0.04] p-3.5 text-left hover:bg-white/[0.07]"
        >
          <span
            className={`mt-px grid size-[22px] shrink-0 place-items-center rounded-full border-[1.5px] ${
              autoClip ? 'border-accent bg-accent text-on-accent' : 'border-[#7b88a6]'
            }`}
          >
            {autoClip && <Check size={13} strokeWidth={3} aria-hidden />}
          </span>
          <span className="flex flex-col gap-1">
            <span className="text-sm font-semibold">Find clips when the import finishes</span>
            <span className="text-xs leading-relaxed text-muted">
              Uses your last Find clips settings: {describePrefs(prefs)}. You can change them from a video's Find clips button.
            </span>
          </span>
        </button>
      </div>
    </Modal>
  )
}
