# Clipping App: guide for coding agents

A desktop app that turns long videos (a local file or a link) into short vertical clips. It finds
clips automatically, then lets the user trim them, reframe them (manual crop, face tracking, or
fit with a blurred background), add captions, tighten them (remove "um"s and long pauses) and
batch-export them. Everything runs locally; there is no cloud service and no AI scoring.

Read this file first. It is meant to save you from re-reading the codebase to find your way around.
Keep it accurate: when you add a module, an endpoint, an event or a convention, update the
relevant section here in the same change.

## Driving the app: use the `clip` command, not screen clicks

To *do* something with the app (import videos, make clips, export, make a demo video), use
`scripts/clip.mjs`. It calls the engine of the **running** app window directly, so a whole task
takes seconds and the window updates live while the user watches. Only use computer use or
screenshots to check a UI change itself.

```bash
node scripts/clip.mjs status                          # is the app running? (exit code 3 = start it with `npm run dev`)
node scripts/clip.mjs project new "GTA comparison"    # → {"id": 3, ...}
node scripts/clip.mjs import 3 "E:\clips\gta5.mp4" "https://youtu.be/..." --wait
node scripts/clip.mjs show 3                          # bring the project up in the window
node scripts/clip.mjs clip add 7 0:42 0:51 --title "Car jacking"
node scripts/clip.mjs clip frame 12 9:16 manual --crop 0.34,0,0.32,1
node scripts/clip.mjs export 12 --aspect 9:16 --out "E:\out" --wait
node scripts/clip.mjs preview "E:\out\clip.mp4"       # one contact-sheet JPG of frames; open it with the Read tool
node scripts/clip.mjs api GET /projects/3/exports     # any endpoint (see "REST API" below)
node scripts/clip.mjs help                            # every command and option
```

- Results are JSON on stdout; progress (from `--wait` and `wait`) goes to stderr. Exit codes:
  0 ok, 1 failed (including a failed job), 2 bad usage, 3 app not running.
- Call it with `node scripts/clip.mjs` (or `npm run -s clip -- ...`). Plain `npm run clip` prints
  npm's banner on stdout and breaks JSON parsing.
- In Git Bash, write `api` paths **without** the leading slash (`api GET sources/6`): Git Bash
  rewrites `/sources/6` into a Windows path before the tool sees it. The tool adds the slash itself.
- How it connects: while the engine runs, the dev app writes `{url, token, videos_dir, ...}` to
  `%APPDATA%\Clipping App Dev\engine.json` and deletes it when the engine stops. The tool only
  ever connects to the dev app, so it can't touch the user's real projects by accident. The
  installed app writes no file unless started with `CLIP_ENABLE_BRIDGE=1`, and the tool uses it
  only with `CLIP_APP=installed`. To point it elsewhere, set `CLIP_ENGINE_FILE`, or
  `CLIP_ENGINE_URL` plus `CLIP_ENGINE_TOKEN`. `status` reports which app it reached.
- `show` calls `POST /ui/show`, which broadcasts a `ui_show` event; the window's store then opens
  that project, or that video in the editor. A video that isn't ready yet opens its project instead.
- When you add an engine feature, add a matching `clip` command (or confirm `api` covers it) and
  list it here, so agents never have to fall back to clicking.

## Two processes

```
Electron app (apps/desktop)                           Python engine (engine/)
 main process ── spawns ──────────────────────────▶  run.py → FastAPI on 127.0.0.1:<random port>
   │  passes CLIP_DATA_DIR, CLIP_BIN_DIR,              prints "ENGINE_READY port=N" when listening
   │  CLIP_ENGINE_TOKEN, CLIP_LOG_DIR as env vars
 preload (window.clipping: files, engine status, updates)
 renderer (React) ── REST (x-engine-token header) ─▶  app/api/*.py routers
                  ◀── WebSocket /ws?token= events ──  EventHub.emit(...) from worker threads
                                                       SQLite (clipping.db) + per-project media folder
                                                       FFmpeg/ffprobe from bin/, yt-dlp, faster-whisper, OpenCV
```

- The renderer talks to the engine **directly over HTTP**, not through Electron IPC. IPC is used
  only for things that need Node or the OS: file and folder pickers, opening or revealing files,
  engine start/restart status, logs and auto-updates.
- Every request needs the per-launch token. `<video>`/`<img>` URLs under `/media/` carry it as
  `?token=` (see `EngineClient.mediaUrl`). If `CLIP_ENGINE_TOKEN` is unset (engine run on its
  own), auth is off.
- Long work (import, analysis, export) runs in `ThreadPoolExecutor` workers inside "manager"
  classes. Workers write progress to SQLite and broadcast the updated row with
  `events.emit(<event>, dict)`. The UI's store applies these events to its lists.

## Commands (Windows; run from the repo root)

`make` is not installed on this Windows machine. The Makefile only wraps these npm scripts, so use
the npm scripts directly.

| Task | Command |
|---|---|
| First-time setup | `npm install`, then `npm run setup` (creates `engine/.venv`, installs Python dependencies, downloads Electron) |
| Put FFmpeg in `bin/` | `npm run bundle:ffmpeg` (copies from PATH), or `npm run bundle:ffmpeg -- <folder containing ffmpeg.exe>` |
| Run the app (dev) | `npm run dev` (electron-vite: renderer on http://localhost:5173, then Electron starts the engine itself) |
| Type-check the UI | `npm run typecheck` |
| Desktop tests | `npm run test:desktop` (node:test; main-process logic that doesn't need Electron) |
| Engine tests | `npm run test:engine` (pytest in the venv; extra args pass through, e.g. `npm run test:engine -- tests/test_editing.py -k export`) |
| Drive the running app | `node scripts/clip.mjs <command>` (see "Driving the app" above) |
| Run the engine alone | `cd engine && .venv/Scripts/python run.py --port 8765` (no auth, data in `.data/`) |
| Build the installer | `npm run dist` (collects licenses, PyInstaller engine + electron-builder) |

Prerequisites: Node 22.12+, Python 3.11+, FFmpeg. On this machine FFmpeg was installed with
`winget install Gyan.FFmpeg` and copied into `bin/` (git ignores `bin/`).

Where data lives:
- Development app: `%APPDATA%\Clipping App Dev\data\` (`clipping.db` plus `projects/<project_id>/sources/<source_id>/`)
- Installed app: `%APPDATA%\Clipping App\data\`
- Engine run on its own: `<repo>/.data/`
- Logs: the Electron logs folder (`app.getPath('logs')`), including `engine.log`

There is no hot reload for the engine. After changing Python code, restart `npm run dev`, or use
the engine restart button in the System check panel on the home screen.

## Repository map

```
apps/desktop/src/
  main/index.ts        window, IPC handlers (file pickers, open/reveal files), app lifecycle
  main/engine.ts       spawns the engine (dev: engine/.venv python run.py; packaged: clipping-engine.exe), waits for ENGINE_READY,
                       writes/removes engine.json (connection file for scripts/clip.mjs)
  main/updater.ts      electron-updater (GitHub releases); updatePolicy.ts decides what it may do unasked (signed builds only)
  preload/index.ts     exposes window.clipping (typed by ClippingBridge in shared/types.ts)
  shared/types.ts      types shared by main, preload and renderer (EngineStatus, ClippingBridge)
  renderer/src/
    App.tsx            top-level screens: Projects → ProjectView → EditorView, plus modal dialogs
    store.ts           Zustand store: ALL engine calls and state; onEngineEvent applies WebSocket events
    lib/api.ts         EngineClient (one method per endpoint) + every API type (Source, Clip, ExportJob…)
    lib/aspects.ts     aspect math and cropAt (mirrors engine/app/reframe/track.py crop_at)
    lib/time.ts, format.ts   frame/time and display helpers
    components/        ProjectView, SourceCard, ImportPanel, ExportDialog, ExportsPanel, AutoClipDialog, SystemCheck…
    components/editor/ EditorView (one source), Stage (video + crop/caption overlays), Timeline, ClipPanel, CaptionsPanel, CropOverlay

engine/
  run.py               entry point: binds the port, prints ENGINE_READY, runs uvicorn
  app/main.py          create_app(): token middleware, CORS, /health, /ws, includes routers, starts managers
  app/config.py        Settings from CLIP_* env vars (data_dir, bin_dir, token, models_dir)
  app/db.py            SQLite + MIGRATIONS list (append-only; PRAGMA user_version)
  app/events.py        EventHub: thread-safe emit() to all WebSocket clients
  app/ffmpeg.py        locate ffmpeg/ffprobe (env override → bin/ → PATH), list hardware encoders
  app/aspects.py       ASPECTS (9:16, 4:5, 1:1, 16:9, 4:3), output_size, normalized crop ↔ pixels
  app/sources.py, clips.py   row → API dict helpers (clips include their per-aspect "formats")
  app/ingest.py        IngestManager: download (yt-dlp) → probe → poster → proxy → thumbnails/waveform
  app/exports.py       ExportManager: render queue, GPU→CPU fallback, captions burn-in/SRT, ZIP batches
  app/api/             routers: projects, sources (+ /media/...), clips, analysis, captions, exports, ui (/ui/show)
  app/media/           blocking FFmpeg work: probe, download, transcode (proxy/poster), timeline assets, render
  app/analysis/        auto clipping: transcribe → signals → candidates → scoring → finder; manager = background job
  app/reframe/         face detection (YuNet), speaker detection, smooth shot-aware crop paths
  app/captions/        cues from words, styles/templates, ASS (burn-in) and SRT output
  app/edit/            Tighten: cut plan (fillers/pauses) and TimeMap (source time → tightened time)
  models/              bundled YuNet face model
  tests/               pytest; conftest makes synthetic videos with FFmpeg; speech tests use Windows TTS

scripts/               clip.mjs (agent CLI for the running app), setup, bundle-ffmpeg, run-engine-tests, build-engine (PyInstaller), paths.mjs
                       collect-licenses.mjs gathers license texts for the installer (`licenses/` holds the ones no package carries);
                       ensure-engine.mjs creates/checks the device-local venv before dev and packaging;
                       engine/check_dependencies.py validates installed versions without third-party imports
PLAN.md                product plan and roadmap. Its "Folder Structure" section is outdated; trust the map above.
```

## Data model (SQLite, see `engine/app/db.py`)

- `projects` → `sources` (an imported video: status, probe info, proxy/poster paths)
- `sources` → `clips` (start_ms/end_ms in source time, title, score, reasons, `edit_json` holding Tighten settings)
- `clips` → `clip_formats` (one per aspect: `mode` = manual | smart | fit, `crop_keyframes_json`, `options_json` for fit style or tracking stats)
- `clip_formats` → `export_jobs` (preset_json, status, progress, output_path); `export_batches` group jobs for ZIP output
- `analyses` (latest auto-clip run per source), `caption_styles` (one per project), `clip_captions` (the user's word edits)

## REST API (`engine/app/api/`)

| Router | Endpoints |
|---|---|
| projects | `GET/POST /projects`, `GET/DELETE /projects/{id}` |
| sources | `GET/POST /projects/{id}/sources`, `GET /sources/{id}`, `POST /sources/{id}/cancel`, `POST /sources/{id}/retry`, `DELETE /sources/{id}`, media: `/media/sources/{id}/thumbs`, `/waveform`, `/{kind}` (proxy, poster) |
| clips | `GET /sources/{id}/clips`, `GET /projects/{id}/clips`, `POST /sources/{id}/clips`, `PATCH /clips/{id}`, `GET /clips/{id}/cut-plan`, `PUT /clips/{id}/formats/{aspect like 9x16}`, `DELETE /clips/{id}` |
| analysis | `POST /sources/{id}/analyze`, `GET /sources/{id}/analysis`, `GET /projects/{id}/analyses`, `POST /sources/{id}/analysis/cancel`, `GET /sources/{id}/transcript`, `POST /clips/{id}/replace` |
| captions | `GET /caption-templates`, `GET/PUT /projects/{id}/caption-style`, `GET/DELETE /clips/{id}/captions`, `POST /clips/{id}/captions/edit`, `POST /sources/{id}/transcribe` |
| ui | `POST /ui/show` `{project_id}` or `{source_id}` (emits `ui_show`) |
| exports | `POST /exports`, `GET /projects/{id}/exports`, `POST /exports/{id}/cancel`, `POST /exports/{id}/retry`, `DELETE /projects/{id}/exports` (clear finished), `GET /projects/{id}/export-batches` |

WebSocket events (names passed to `events.emit`, handled in `store.ts` `onEngineEvent`):
`source`, `clip`, `clip_deleted`, `analysis`, `transcript`, `caption_style`, `export`, `export_batch`, `ui_show`.

## Key flows

- **Import:** `POST /projects/{id}/sources` → `IngestManager` worker → emits `source` as status goes
  queued → downloading → probing → processing → ready. A 480p constant-frame-rate proxy is used for
  playback and analysis; exports always read the original file.
- **Auto clip:** `POST /sources/{id}/analyze` → `AnalysisManager` → transcribe (faster-whisper,
  model downloaded on first use) → scene cuts and loudness on the proxy → candidates → score by
  mode (talking / action / even) → replaces the source's *suggested* clips, emitting `clip` and `analysis`.
- **Framing:** `PUT /clips/{id}/formats/{aspect}`. Smart mode is tracked lazily: at export time, if
  the keyframes don't cover the clip (`keyframes_cover`).
- **Export:** `POST /exports` creates one job per (clip × aspect) → `ExportManager._run` → builds an
  FFmpeg filter graph (`media/render.py: build_video_filter`) → `render_clip` writes `name.partial.mp4`,
  then renames it. Hardware encoders are tried first, with an automatic retry on CPU.

## Conventions

- **Times** are integer milliseconds in *source* time everywhere (DB, API, UI), unless a name says
  otherwise. Tightened clips use `TimeMap` to convert to output time.
- **Crops** are rectangles normalized to the displayed source frame (0..1, after rotation), never
  pixels, so they don't depend on the proxy or original resolution.
- **Blocking media work** goes in `app/media/` or the domain package, takes a `CancelToken`, and
  raises `MediaError` with a message meant for the user (the API returns it as a 422).
  Cancellation raises `Cancelled`.
- **Schema changes:** append a new string to `MIGRATIONS` in `db.py`. Never edit a migration that
  has already shipped.
- **Adding an endpoint end to end:**
  1. Pydantic model and route in `engine/app/api/<area>.py` (register new routers in `main.py`)
  2. `EngineClient` method and types in `renderer/src/lib/api.ts`
  3. Store action in `store.ts` (wrapped in `run(...)` so errors reach the banner)
  4. Handle any new WebSocket event in `onEngineEvent`
  5. Tests in `engine/tests/` using the `client` / `project` / `short_video` fixtures
- **Background jobs** follow the `ExportManager` pattern: `submit` → worker `_run` → `_update(...)`
  writes the row and emits it. `start()` marks rows left running by a crash as failed;
  `shutdown()` cancels workers.
- **UI:** Tailwind v4 with theme colors defined in `renderer/src/index.css` (`bg`, `panel`,
  `panel-2`, `control`, `line`, `ink`, `muted`, `link`, `accent`, `accent-hover`, `accent-subtle`,
  `danger`, `success`, `warning` and their `-subtle` variants), used as `bg-panel`, `border-line`,
  `text-muted` and so on. Don't use raw hex colors. Dialogs are opened through store flags (`exportDialog`,
  `autoClipDialog`) and rendered in `App.tsx`. Components read state with `useApp(selector)` and
  call actions through `useApp.getState()`.
- **Dialogs** use the `Modal` frame (`components/Modal.tsx`: backdrop, header, close button,
  Escape/click-outside to close, focus kept inside). To ask "are you sure?", call
  `await confirmAction({ title, message, confirmLabel, danger })` from `lib/confirm.ts`;
  never the browser's `confirm()`/`alert()`.
- **Icons** come from `lucide-react`, at `size={14}` in `text-xs` buttons and `size={16}` in `text-sm`
  ones, with `aria-hidden` when a text label is next to them (icon-only buttons get an `aria-label`).
  A button with an icon is `inline-flex items-center gap-1.5`.
- **Code style:** comments explain *why*, in plain sentences. Python uses type hints and
  dataclasses; long FFmpeg argument lists are marked `# fmt: skip`. TypeScript is strict, with no
  semicolons, single quotes and 2-space indentation.

## Gotchas

- `npm run dev` runs `ensure-engine.mjs` before Electron: it discovers Python 3.11+ (or
  `CLIP_PYTHON`), creates the local venv if needed, and installs missing/changed requirements.
  It needs internet for installation and `node_modules` (`npm install`). `npm run setup` also
  installs test/build dependencies and the Electron binary. Do not copy venvs between devices.
- Paths come from the clone and OS user folders. The desktop engine honors `CLIP_DATA_DIR`
  and `CLIP_BIN_DIR`; individual tool overrides and `CLIP_MODELS_DIR` are passed through.
- Without FFmpeg in `bin/` (or on PATH) the UI loads, but imports and exports fail. `/health` and
  the SystemCheck panel report it.
- The engine port is random on every launch. Find it in the dev console output, or in the engine
  status sent to the renderer; don't hard-code 8765 except when running the engine on its own.
- FFmpeg filter graphs are written to a file (`-/filter_complex`) because smart-crop expressions
  can exceed Windows' command-line length limit. Subtitles and fonts are referenced by relative
  name from a temporary working directory to avoid escaping Windows paths inside filters.
- Engine tests need FFmpeg in `bin/`; tests that need it are skipped otherwise (`needs_ffmpeg`).
  Speech tests need Windows text-to-speech.
