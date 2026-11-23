# Fix report

Date: 2026-11-24. Covers `AUDIT_REPORT.md`, plus N-01 to N-03 found while writing `SHORTS_DESIGN.md`. Baseline commit: `f9b4e31`. Phase 0 of the Shorts work was not started.

## 1. Result

| | Baseline | After |
|---|---|---|
| Engine tests passed | 105 | **253** |
| Engine tests failed | 0 | **0** |
| Engine tests blocked by this PC (error) | 9 | 9 (the same ones) |
| Engine tests skipped | 0 | 0 |
| Desktop tests (`npm run test:desktop`, new) | none | 11 passed, 0 failed |
| Type-check, desktop build | ok | ok |

- **The 41 tests skipped during the audit** (no FFmpeg): **32 now run and pass, 9 are blocked**, before and after.
- **Why 9 are blocked.** They need `engine/tests/make_speech.ps1`. Windows refuses to run it because the file is marked as downloaded from the internet. I did not bypass or change that. To run them:
  ```powershell
  Unblock-File "E:\Projects-Products\smart clips\engine\tests\make_speech.ps1"
  ```
  As a substitute I ran that whole path once by hand, with the real `tiny` model and a short spoken clip of my own: transcription, clip finding, Replace, burned captions, SRT, ZIP and Tighten all worked.
- **Nothing that passed before fails now.** One baseline test was rewritten: `test_trim_window_selects_exact_frames` tested a function N-01 replaced, and is now `test_clip_frames_and_seek_select_exact_frames`, with the same frame counts. Test clients now use `127.0.0.1`, and one blocked test reads a renamed cache file.

## 2. Findings

| Finding | Status | Commit | Test |
|---|---|---|---|
| F-01 CPU fallback for speech | Fixed | `d0cddc8` | `test_transcribe_device.py`; run on the RTX 5060 |
| F-02 Variable frame rate in Tighten | Fixed | `4bcf7fb` | `test_sync.py` (under 1 frame at every flash) |
| F-03 Caption edits on tightened clips | Fixed | `0e362c5` | `test_caption_edits.py` |
| F-04 Job ids and folders | Fixed | `82d5b10` | `test_job_isolation.py` |
| F-05 Unsigned auto-update | Fixed | `db7a30a` | `updatePolicy.test.mjs` |
| N-01 Repeated and dropped frames | Fixed | `ece8b7c` | `test_cut_frames.py` |
| N-02 VFR not detected in MKV | Fixed | `c5db992` | `test_probe.py` |
| N-03 Seeking in `.ts` | Fixed | `b707c81` | `test_cut_frames.py` (frames and A/V sync) |
| F-23 FFmpeg licensing | Fixed, with a release step (section 3) | `5f46c27` | `licenses.test.mjs` |
| F-06 Standalone engine security | Fixed | `3d992a6` | `test_engine.py` |
| F-07 Playlist links | Fixed | `dbedadc` | `test_download.py` (local server) |
| F-08 One-segment Tighten | Fixed | `f016029` | `test_tighten.py` |
| F-12 Tighten audio drift | Fixed | `d0e371c` | `test_sync.py` (36 cuts, AAC and FLAC) |
| F-13 Fillers in other languages | Fixed | `98e6ecb` | `test_caption_edits.py` |
| F-15 FFmpeg after an error | Fixed | `c08e3fa` | `test_processes.py` |
| F-16 ZIP batches | Fixed | `b226bd1` | `test_job_isolation.py` |
| F-17 Migrations | Fixed | `91c0b09` | `test_migrations.py` |
| F-19 Event reconnect | Fixed | `21f9dcb` | `events.test.mjs` |
| F-20 Caption style values | Fixed | `53aa668` | `test_caption_edits.py` |
| F-21 Scoring time | Fixed | `889ab62` | `test_clipfinder.py` (3 h in about 1 s) |
| F-24 Electron | Fixed (45.4.1) | `c3ea7e5` | Real app started and used |
| F-14 FFmpeg after quitting | Fixed, real (section 3) | `8893c48` | `test_processes.py`, real app |
| F-25 HDR | Fixed, real (section 3) | `e7597f0` | `test_hdr.py`, real app |
| F-09 Deleting first/last caption | Fixed | `f6a79a6` | `test_caption_edits.py` |
| F-10 Edits outside a trim | Fixed | `0056afa` | `test_caption_edits.py` |
| F-11 Default framing | Fixed | `88c2dcc` | `test_job_isolation.py` |
| F-18 Failed measurements cached | Fixed | `8b85faf` | `test_signal_cache.py` |
| F-22 Memory | **Partially fixed** | `1140e04` | `test_signal_cache.py` |
| F-44 Non-ASCII token (one-liner) | Fixed | `3d992a6` | `test_engine.py` |
| F-26 to F-43, F-45, F-46 | Not touched, except as noted in section 4 | | |

F-12 was committed before F-02 because F-02's "under one frame" test needs both. All new regression tests were checked against the code before their fix where that was possible; the ones for the reported bug failed there.

## 3. Choices and verifications you asked about

**F-01.** Missing `cublas64_12.dll` is detected before a model loads. A short warm-up inference catches anything else. The reason appears in System check, in the progress text and in the log. On your GPU the baseline fails with the cuBLAS error; the fixed code transcribes on the CPU, also with the up-front check disabled. Nothing was installed.

**F-02, N-01 to N-03.** I did not convert videos on import: that would re-encode originals, cost quality and disk, and take long for VODs. Instead every render puts frames on a constant grid before anything counts them. Before: 14 of the 19 first N-01 checks failed. After: zero repeated, dropped or neighbouring frames in MP4, MKV, WebM and `.ts` at four frame rates, and exports match the preview frame for frame.

**F-04.** Ids are never reused. Sources keep a folder of their own, exports get a private work folder, and a worker can write state only while it owns the job. Existing databases are migrated, with a copy kept as `clipping.db.v7.bak`.

**F-05.** Unsigned builds no longer download or install anything on their own. They announce a version; Download is a click, and installing asks for confirmation that says the maker can't be verified. Signed builds keep updating automatically, because then electron-updater does check the publisher. I chose this over removing updates because it keeps them available and needs no code change once you sign.

**F-23.** Kept the GPL build and bundled the texts. An LGPL-only FFmpeg has no libx264 or libx265, which every preview and the CPU export fallback need.
- What changes: the installer carries `licenses/`, and `npm run dist` stops if FFmpeg's license text is missing.
- **You must still** attach the matching FFmpeg source (or host it) when you publish a release. The notices say so.
- The project itself still has no license; that's your choice to make.
- I did not build the installer, so the packaged folder is unchecked.

**F-14.** Real. In the development app FFmpeg does stop, but only because Python's venv launcher happens to clean up. Without it, as in the installed app, a render ran its full 31 s after the engine was killed. Now it ends in 0.1 s. In the real app: quit during an export, FFmpeg gone within 2 s, leftovers cleared at the next start.

**F-25.** Real. In the real app HLG and PQ came out 8-bit but still tagged HDR. Average color error against the SDR original, out of 255: HLG 24.7, PQ 41.3. After the fix: 0.3 and 0.9. Test clips were generated; no phone footage was used.

## 4. Deferred

| What | Why |
|---|---|
| F-22: transcribing a file still holds its audio (about 230 MB per hour) | Transcribing in windows is a redesign. Loudness no longer grows with length, and decoding keeps one copy instead of up to three |
| F-21: candidate texts (216 MB in the widest 3 h case) | Only the time was fixed |
| F-11: defaults saved by earlier versions | Can't be told apart from your own choices, so they stay |
| F-13: filler prompt with language auto-detect | The language isn't known when it's given; only explicit non-English skips it |
| F-07 on real sites | Tested with a local server only |
| Low and Info findings | Per your rule. Some were partly covered on the way: F-29 (scene measurement once), F-31 (work folder, partial ZIP), F-32 (retry race) |

## 5. New discoveries

| # | What | State |
|---|---|---|
| N-04 | **The engine writes its per-launch token to `engine.log`**: uvicorn logs the WebSocket address with `?token=…`. The audit wrongly said the token isn't logged. The token is useless after the engine stops | Not fixed, outside the list. Suggested: drop that log line |
| N-05 | The audit also wrongly listed ordinary cuts as fine (now N-01). **Clips exported before this, from MKV or WebM especially, can have repeated frames; export them again** | Information |
| N-06 | Videos imported before keep their old frame-rate flag and, for HDR, their old preview. Exports are correct; re-import to refresh the preview | Information |
| N-07 | The old waveform code could hang forever when it failed; it hung my test | Fixed in F-15 |
| N-08 | electron-updater skips the signature check entirely when a build has no publisher (confirmed in its source) | Covered by F-05 |
| N-09 | Loading a speech model contacts Hugging Face every time, even when it's already downloaded | Planned for Phase 0 (offline) |
| N-10 | HDR exports and imports do extra color work and will be slower. Not measured | Information |
| N-11 | During the Electron update a file in `node_modules/electron` was briefly locked by another program, and the folder `%APPDATA%\Clipping App Dev` changed at 00:41, while I was not running the app. If you had started it then, that explains both | Information |

## 6. Files and safety

- Everything installed, downloaded or generated for this pass is inside the project folder, mostly in the git-ignored `.cache/` (3.7 GB: FFmpeg download, speech model, Electron and pip caches, test videos, copies of old code). Delete it when you like; it is rebuilt when needed. `bin/`, `node_modules/` and `engine/.venv/` are in use.
- Before your safety rules, the audit made a scratch folder at `E:\DevTools\temp\claude\…\scratchpad`, with a Python environment. It's outside the project and safe to delete.
- The interrupted `winget` command installed nothing. I removed its empty temp folder.
- All test videos were generated and under 2 minutes. None of your videos were opened.
- The app was run with its data inside the project, not in `%APPDATA%`. No system, driver or GPU setting was changed.
