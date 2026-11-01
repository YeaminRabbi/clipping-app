# Clipping App

Desktop app that turns a long video (link or local file) into short clips: automatic clip finding,
preview and trim, smart reframing for phone / Instagram / desktop / tablet sizes, optional captions,
and batch export. Everything runs locally. See [PLAN.md](PLAN.md) for the full plan.

## Layout

```
apps/desktop/   Electron + React UI (electron-vite, Tailwind, Zustand), installer config
engine/         Python processing engine (FastAPI on localhost, SQLite, FFmpeg, faster-whisper, OpenCV)
engine/models/  Bundled face detection model
bin/            Bundled ffmpeg / ffprobe (copied in, not committed)
scripts/        Setup and build helpers
```

The Electron main process starts the engine on a random free port with a per-launch token, and the
renderer talks to it over HTTP (commands) and WebSocket (progress events). The engine owns the
SQLite database, stored in the app's user-data folder.

## Requirements

- Node.js 22.12+
- Python 3.11+
- FFmpeg and FFprobe in `<project drive>:\\Dev Tools\\FFmpeg`, or set `CLIPPING_APP_FFMPEG_DIR`.

For an E:-contained Windows development shell, put `E:\Dev Tools\NodeJS` first on `PATH` and set
`npm_config_cache=E:\Dev Tools\npm-cache`. Setup prefers `E:\Dev Tools\Python312\python.exe`;
override it with `CLIPPING_APP_PYTHON`. Desktop scripts automatically place Electron caches,
electron-builder caches, and temporary files under `<project drive>:\Dev Tools`.

## Getting started

```bash
npm install
npm run setup          # Python venv + engine deps + Electron binary
npm run bundle:ffmpeg  # prefers <project drive>:\Dev Tools\FFmpeg, then PATH; copies into bin/
npm run dev
```

## Other commands

| Command | What it does |
|---|---|
| `npm run typecheck` | Type-check main, preload and renderer |
| `npm run build` | Production build of the desktop app into `apps/desktop/out` |
| `npm run test:engine` | Run the engine's pytest suite (speech tests use Windows text-to-speech) |
| `npm run build:engine` | Build the engine into `engine/dist/clipping-engine` with PyInstaller and smoke-test it |
| `npm run dist` | Build the engine and the Windows installer into `apps/desktop/release` |
| `npm run release` | Same, then publish the installer to GitHub Releases (see below) |

Run the engine on its own (auth disabled, data in `.data/`):

```bash
cd engine && .venv/Scripts/python run.py --port 8765
```

## Building the installer

```bash
npm run dist
```

This produces `apps/desktop/release/Clipping-App-Setup-<version>.exe` (about 290 MB; the app
installs to about 920 MB because it bundles the Python engine, FFmpeg and OpenCV). The installer
isn't code-signed yet, so Windows SmartScreen will warn on first run until it's signed with a
certificate (set `CSC_LINK` / `CSC_KEY_PASSWORD` before building).

Speech models aren't in the installer: each one downloads the first time it's used (75 / 145 / 480 MB).

## Publishing an update

Installed apps check GitHub Releases of `YeaminRabbi/clipping-app` on startup and every 6 hours,
download a newer version in the background, and offer "Restart to update".

1. Bump `version` in `apps/desktop/package.json` (e.g. `0.1.0` → `0.2.0`).
2. Create a GitHub token with `repo` scope and set it: `set GH_TOKEN=...`
3. Run `npm run release`. It uploads the installer, its blockmap and `latest.yml` to a GitHub release
   for that version. Publish the release if it was created as a draft.

## Where things are stored (Windows)

| What | Installed app | Development (`npm run dev`) |
|---|---|---|
| Projects, database, previews, transcripts | `%APPDATA%\Clipping App\data` | `<project drive>:\Dev Tools\Clipping App Dev\data` |
| Speech models and app caches | `%APPDATA%\Clipping App\data\models` | `<project drive>:\Dev Tools\Clipping App Dev\data` |
| Logs (`main.log`, `engine.log`) | `%APPDATA%\Clipping App\logs` | `<project drive>:\Dev Tools\Clipping App Dev\logs` |
| Chromium session/cache/crash data and temporary files | Electron defaults | `<project drive>:\Dev Tools\Clipping App Dev` |

The System check panel has an **Open logs folder** button. Exported videos go wherever you choose
(development defaults to `<data root>\exports\<project>`); uninstalling keeps projects and exports.

Set `CLIPPING_APP_DATA_ROOT` before launch to move all application-controlled persistent data,
logs, Chromium session/cache data, updater downloads, crash dumps, default exports, and temporary files. Installed builds keep their
normal platform location unless this variable is set. `CLIPPING_APP_FFMPEG_DIR` overrides the
FFmpeg/FFprobe directory, and `CLIPPING_DEV_TOOLS_ROOT` overrides the development-tools root used
by setup/build scripts.
