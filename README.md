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
- FFmpeg (only needed to copy into `bin/`; e.g. `winget install Gyan.FFmpeg`)

## Getting started

```bash
npm install
npm run setup          # Python venv + engine deps + Electron binary
npm run bundle:ffmpeg  # copy ffmpeg/ffprobe from PATH into bin/
npm run dev
```

`npm run dev` checks the local Python environment before opening Electron. It creates the venv
if needed and installs missing or changed runtime dependencies, including after a `git pull`.
The first run needs internet access; subsequent launches skip installation when requirements
are satisfied. `npm run setup` also installs the test/build tools and Electron binary.

Paths are resolved from the clone and the current user's OS folders; no username, drive or
GPU is required in configuration. On Windows, setup tries the `py` launcher and then Python
on PATH; elsewhere it tries `python3` and `python`. Python must be 3.11 or newer.
FFmpeg and ffprobe are discovered from explicit overrides, then `bin/`, then PATH.
Hardware export falls back to CPU when an encoder cannot run on the current device.

Optional environment variables (set before setup/start):

| Variable | Purpose |
|---|---|
| `CLIP_PYTHON` | Python executable used to create the local venv when it is missing or unusable |
| `CLIP_DATA_DIR` | Store projects and the database in a custom folder instead of the OS app-data folder |
| `CLIP_BIN_DIR` | Folder containing FFmpeg and ffprobe |
| `CLIP_FFMPEG_PATH`, `CLIP_FFPROBE_PATH` | Override either executable individually |
| `CLIP_MODELS_DIR` | Custom speech-model cache folder |

Do not copy `engine/.venv` or `node_modules` between devices; recreate them in each clone.
The packaged Windows installer bundles Python and its dependencies, so end users do not need setup.

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
and what happens next depends on whether the build is code-signed:

- **Signed**: a newer version downloads in the background, its publisher is checked against the installed
  app's, and "Restart to update" appears (it also installs when the app is closed).
- **Not signed** (the case today): nothing downloads or installs by itself. The header says a version is
  available; "Download" fetches it and "Restart to update" asks for confirmation, because the app has no
  way to check who made it.

1. Bump `version` in `apps/desktop/package.json` (e.g. `0.1.0` → `0.2.0`).
2. Create a GitHub token with `repo` scope and set it: `set GH_TOKEN=...`
3. Run `npm run release`. It uploads the installer, its blockmap and `latest.yml` to a GitHub release
   for that version. Publish the release if it was created as a draft.

## Where things are stored (Windows)

| What | Installed app | Development (`npm run dev`) |
|---|---|---|
| Projects, database, previews, transcripts | `%APPDATA%\Clipping App\data` | `%APPDATA%\Clipping App Dev\data` |
| Speech models | `%APPDATA%\Clipping App\data\models` | `%APPDATA%\Clipping App Dev\data\models` |
| Logs (`main.log`, `engine.log`) | `%APPDATA%\Clipping App\logs` | `%APPDATA%\Clipping App Dev\logs` |

The System check panel has an **Open logs folder** button. Exported videos go wherever you choose
(default `Videos\Clipping App\<project>`); uninstalling keeps projects and exports.
