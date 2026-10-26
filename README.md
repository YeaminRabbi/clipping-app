# Clipping App

Desktop app that turns a long video (link or local file) into short clips, with preview, trim,
aspect-ratio reframing and batch export. See [PLAN.md](PLAN.md) for the full plan.

## Layout

```
apps/desktop/   Electron + React UI (electron-vite, Tailwind, Zustand)
engine/         Python processing engine (FastAPI on localhost, SQLite)
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

## Other commands

| Command | What it does |
|---|---|
| `npm run typecheck` | Type-check main, preload and renderer |
| `npm run build` | Production build of the desktop app into `apps/desktop/out` |
| `npm run test:engine` | Run the engine's pytest suite |

Run the engine on its own (auth disabled, data in `.data/`):

```bash
cd engine && .venv/Scripts/python run.py --port 8765
```
