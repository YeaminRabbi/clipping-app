# Clipping App — Project Plan

A desktop app that takes a video link or a local file, automatically segments it into short clips
(similar to Opus Clip), lets the user preview/trim/reframe each clip, and batch-exports them.

## Decisions

| Decision | Choice |
|---|---|
| Platform | **Desktop** (Windows first, macOS later) — frame-accurate local FFmpeg, GPU encoding, no uploads |
| Clip selection | **Local heuristic scoring — no AI/LLM scoring** (fully offline, free, deterministic) |
| Auto captions | **Optional** — off by default, toggled per project/export |

## Tech Stack

| Layer | Choice |
|---|---|
| Shell | Electron + React + TypeScript + Vite |
| UI | Tailwind + shadcn/ui, Zustand |
| Timeline / player | Custom canvas timeline, wavesurfer.js, HTML5 `<video>` on proxy files |
| Engine | Python sidecar (FastAPI on localhost, packaged with PyInstaller) |
| Video I/O | FFmpeg / ffprobe (bundled) |
| Link ingest | yt-dlp (bundled, self-updating) |
| Transcription | faster-whisper (word timestamps; GPU if available, CPU fallback) — used for boundary snapping and optional captions |
| Scene detection | PySceneDetect |
| Audio analysis | FFmpeg `ebur128` / librosa (loudness, silence) |
| Smart reframe | MediaPipe face detection + smoothing |
| Storage | SQLite + per-project media folder |
| Jobs | Local job queue, progress over WebSocket |

## Architecture

```
┌──────────────── Electron (React UI) ─────────────────┐
│ Import → Clip Settings → Review Grid → Editor → Export│
└───────────────▲───────────────────────┬──────────────┘
       progress (WS)               REST commands
┌───────────────┴───────────────────────▼──────────────┐
│        Python Engine (FastAPI, localhost)             │
│ Ingest │ Transcribe │ Analyze │ Score │ Reframe │ Render│
│           FFmpeg · yt-dlp · Whisper · MediaPipe        │
└──────────────────────────┬───────────────────────────┘
                   SQLite + project media folder
```

## Clipping Pipeline (no AI scoring)

1. **Ingest** — URL via yt-dlp (best quality) or local file (referenced, not copied); ffprobe metadata.
2. **Normalize** — 480p proxy for scrubbing; convert VFR sources to CFR so cuts are frame-exact.
3. **Transcribe** — faster-whisper word timestamps (skippable for music/no-speech videos).
4. **Analyze signals** (per second of video):
   - Scene cuts (PySceneDetect)
   - Loudness / energy peaks and silence gaps
   - Speech density (words per second)
   - Face presence
5. **Generate candidates** — sliding windows within the user's min/max duration, starting on a
   sentence start and ending on a sentence end / silence gap.
6. **Heuristic score** (0–100, weighted sum, normalized):

   | Signal | Effect |
   |---|---|
   | Energy peaks / loudness variance | + |
   | Speech density (steady talking) | + |
   | Scene-change activity (Action mode) | + |
   | Face visible most of the clip | + |
   | User keyword matches in transcript | ++ |
   | Ends on a complete sentence | + |
   | Long silences inside the clip | − |
   | Starts mid-thought ("and", "but", "so", "because") | − |

   **Scoring modes** (presets that change the weights):
   - **Talking** — podcasts, interviews, lectures (speech + keywords weighted)
   - **Action** — gaming, sports, vlogs (energy + scene changes weighted)
   - **Even split** — no scoring; divides the source into N evenly spaced clips snapped to boundaries
7. **Select N** — top N non-overlapping candidates.
8. **Boundary snap** — nudge in/out to the nearest scene cut / silence gap within ±0.5 s.
9. **Reframe** — compute crop keyframes per target aspect ratio.
10. **Review grid** — clips ranked by score, each showing why it scored (e.g. "high energy, keyword: pricing").

## Feature Specs

### 1. Clip count control
- **Number of clips**: Auto (all candidates above a score threshold) or fixed 1–50.
- **Duration range**: 15–30 s / 30–60 s / 60–90 s / custom.
- **Scoring mode**: Talking / Action / Even split.
- **Keywords** (optional) to boost matching sections.
- **Source range** (optional) to process only part of the video.
- Engine keeps ~2×N candidates so **"Replace this clip"** swaps in the next best instantly.

### 2. Preview & trim editor
- Player with frame-step (←/→, Shift = 1 s), J/K/L shuttle, I/O to set in/out.
- Timeline: thumbnail strip + waveform + transcript overlay.
- Drag in/out handles; snapping to word / scene / frame (toggleable).
- Transcript-based trim: select text to set range.
- Extend beyond the original boundaries into the source.
- Live crop preview for the selected ratio. Undo/redo, "reset to original".

### 3. Aspect ratio / frame selection

| Preset | Ratio | Output |
|---|---|---|
| Phone (Reels/TikTok/Shorts) | 9:16 | 1080×1920 |
| Instagram portrait | 4:5 | 1080×1350 |
| Instagram square | 1:1 | 1080×1080 |
| Desktop / YouTube | 16:9 | 1920×1080 |
| Tablet | 4:3 | 1440×1080 |

Framing modes per clip:
- **Smart** — face tracking with smoothing
- **Manual** — drag/resize crop box, keyframes over time
- **Fit** — whole frame over a blurred or solid background

Apply to one clip or all clips; a clip can be exported in multiple ratios at once.

### 4. Export / download all
- Export all / selected / single.
- Format MP4 (H.264 / H.265); quality Original / High / Medium / target size; fps source/30/60.
- Hardware encoder auto-detect (NVENC / QSV / AMF), CPU fallback.
- Naming template, e.g. `{project}_{index}_{title}_{ratio}.mp4`.
- Output to a folder, optional ZIP.
- Per-clip progress, cancel/retry, ETA; 2–3 renders in parallel depending on hardware.

### 5. Auto captions (optional)
- Off by default; toggle in Clip Settings and per export.
- Reuses the existing Whisper transcript (no extra processing).
- Caption editor: fix words, adjust timing.
- 3–5 style templates (word-by-word highlight, classic subtitle, bold centered); font, color, position.
- Output: burned into the video and/or a sidecar `.srt` file.
- Language auto-detect, manual override.

## Data Model (SQLite)

- **Project**: id, name, created_at, settings_json (clip count, duration range, mode, keywords, captions_enabled)
- **Source**: id, project_id, origin (url|file), url, path, duration, fps, width, height, proxy_path, transcript_path
- **Clip**: id, source_id, start_ms, end_ms, score, score_reasons_json, title, status (suggested|kept|rejected), order
- **ClipFormat**: id, clip_id, aspect, mode (smart|manual|fit), crop_keyframes_json
- **CaptionStyle**: id, project_id, template, font, color, position
- **ExportJob**: id, clip_format_id, preset_json, burn_captions, export_srt, status, progress, output_path, error

## Folder Structure

```
clipping-app/
├─ apps/desktop/            # Electron main + preload
│  └─ renderer/             # React UI
│     ├─ pages/ (Import, Settings, Review, Editor, Export)
│     └─ components/ (Timeline, Player, CropOverlay, ClipCard, CaptionEditor)
├─ engine/                  # Python sidecar
│  ├─ api/                  # FastAPI routes, websocket
│  ├─ pipeline/             # ingest, transcribe, scenes, audio, score, select, reframe, captions, render
│  └─ jobs/                 # queue, workers
├─ bin/                     # ffmpeg, ffprobe, yt-dlp
└─ packaging/               # electron-builder, PyInstaller specs
```

## Roadmap

| Phase | Scope | Est. |
|---|---|---|
| 0. Foundation | Electron + React scaffold, Python sidecar, bundled FFmpeg, SQLite | 1 wk |
| 1. Ingest | URL + file import, metadata, proxies, progress UI | 1 wk |
| 2. Manual MVP | Player, timeline, trim, aspect presets + manual crop, batch export | 2 wk |
| 3. Auto clipping | Whisper, scene + audio analysis, heuristic scoring, modes, select N, snapping | 2 wk |
| 4. Smart reframe | Face tracking, smoothing, fit-with-blur | 1–2 wk |
| 5. Optional captions | Caption toggle, editor, templates, burn-in + SRT | 1–2 wk |
| 6. Polish & ship | Replace clip, HW encoding, naming templates, ZIP, installer, auto-update | 1–2 wk |
| Later | Optional AI scoring, filler-word removal, batch sources, macOS, direct publishing | — |

## Risks

- **VFR sources → imprecise cuts**: normalize to CFR on ingest; re-encode at cut points.
- **Heuristics miss "best moments"**: scoring modes + keywords + "Replace clip" + score reasons; weights tunable in settings. The scorer is a separate module so AI scoring can be added later.
- **Weak PCs**: GPU detection, smaller Whisper model on CPU, analyze on proxy.
- **Link downloads break**: in-app yt-dlp updates. Users must only process content they own or have rights to.
- **App size**: download Whisper models on first run (only needed if transcription/captions are used).
