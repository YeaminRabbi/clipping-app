# Clipping App: Redesign Spec (approved 25 Nov 2026)

Live prototype: https://claude.ai/artifact/1S51cS7FqCScmoHS8UVKSv. The source for each screen is in `screens/`.

## 1. Look: dark navy "liquid glass"

| Token | Value | Use |
|---|---|---|
| `--bg` | `#0a1120` | App background |
| `--ambient-1` | `#23416f`, 55% opacity, blur 140px | Soft glow, top area |
| `--ambient-2` | `#1a2f55`, 70% opacity, blur 140px | Soft glow, bottom right |
| `--glass` | `rgba(58,82,130,0.20)` | Panel fill |
| `--glass-strong` | `rgba(26,40,70,0.72)` | Dialog fill |
| `--glass-header` | `rgba(255,255,255,0.05)` | Panel header strip |
| `--border` | `rgba(255,255,255,0.08)` | Panel border |
| `--highlight` | `inset 0 1px 0 rgba(255,255,255,0.06)` | Top edge sheen on glass |
| `--shadow` | `0 20px 50px rgba(2,6,16,0.45)` | Panel depth |
| `--divider` | `1px dashed rgba(160,180,220,0.18–0.35)` | Row and group separators |
| `--text` | `#eef2fb` | Primary text |
| `--text-muted` | `#9aa7c2` | Secondary text (passes 4.5:1 on navy) |
| `--primary` | `#f1f4fa` on `#0a1120` text | Primary buttons, selected states, progress |
| `--video-bg` | `#060a14` | Preview and timeline (solid, no glass) |
| `--success` | `#4ade80` / badge `#86efac` on 16% fill | Engine ready, "All good" |
| `--warning` | `#fcd34d` | Unsure transcript words, engine starting |
| `--danger` | `#e5484d` / soft `#fca5a5` | Clear data (confirm state) |

- **Font:** Inter. Sizes are 12–13 px for UI, 14–16 px for panel and dialog titles, and 24 px semibold with -0.02em tracking for page titles.
- **Shapes:** fully rounded pills for buttons, inputs, chips, tabs and toggles. 20–24 px radius for panels and dialogs, 12–16 px for inner cards. Icon buttons are circles.
- **Buttons:** Primary is a white pill with navy text. Secondary is a transparent pill with a 1px `rgba(255,255,255,0.22)` border. Danger is red. Selected toggle and tab states are white fill with navy text.
- **Blur rule (performance):** `backdrop-filter: blur(24px) saturate(140%)` goes ONLY on floating elements (sidebar and dialogs). Panels use a translucent fill with no blur. The video preview and timeline are always solid, so footage colours stay true and the GPU isn't redrawing blur during playback.

## 2. Layout

- **Floating sidebar:** 68px wide, 14px from the window edges, 24px radius, glass with blur. From top to bottom:
  - the app logo (white circle with the scissors icon)
  - Home
  - a spacer
  - the engine status dot (green and glowing; opens Settings)
  - Settings

  The active item gets a `rgba(255,255,255,0.12)` circle. Home stays active inside a project and in the editor. There are no project shortcuts and no + button in the sidebar.
- **Content:** starts at 96px from the left, with 30–34px padding.

## 3. Screens and behaviour

### Home (`Main.dc.html`)
- Page title "Projects", a description, and a primary **New project** button (top right).
- Project cards in a responsive grid (`minmax(260px, 1fr)`): frame thumbnail, status badge (clip count, Working, Exported), name and meta line.
- Dropping a video file anywhere in the app opens the New project dialog with that file already added.
- **New project dialog:**
  1. A drop zone ("Drop a VOD here or choose a file").
  2. Once a file is picked, the import starts immediately and shows a progress bar.
  3. The project name auto-fills from the file name and stays editable.
  4. A checkbox, **"Find clips when the import finishes"** (ticked by default), with a summary of the settings (Gameplay stream, 30–60 s, facecam auto, transcript and thumbnails) and a "Change settings" link.
  5. **Create project** is disabled until a file is added. Clicking it navigates to the Project page.

### Project (`Project.dc.html`)
- Breadcrumb "Projects /", project title, then **Add video** (secondary) and **Export N clips** (primary).
- A "Videos" glass panel with a header strip. Each video row has:
  - a thumbnail with the facecam box outline and a duration pill
  - the file name and when it was added
  - actions: **Find clips** (secondary) and **Edit N clips** (primary)
  - chips for resolution and fps, mic track, and facecam.
- **New import, in order:**
  1. The progress bar shows "Importing and preparing preview".
  2. If auto clipping is on, it moves into "Finding clips · step" with these steps: checking facecam → scanning audio for shouts → finding scene changes → transcribing candidates → picking thumbnails.
  3. When done, the row shows "Edit N clips".
  4. The auto-clipping chip can be toggled only while the import is still running.
- **Find clips dialog:** pill toggle groups for Kind (Talking / Action / Gameplay / Even split), Clip length (15–30 / 30–60 / 60–90 s) and Facecam (Detect automatically / Preset / No facecam).

### Editor (`Editor.dc.html`)
- **Top row:** a back button (circle), the project and file name, Shortcuts, and **Export clips**.
- **Preview:** solid background.
  - **Edit framing** shows the 9:16 crop region dashed in white and the facecam box dashed in blue with a "Facecam" label.
  - **Preview output** shows the stacked 9:16 (facecam on top, about 36%, gameplay below).
  - A segmented pill toggle switches between the two.
- **Controls:** a white circular Play button, timecode, Mark In and Mark Out.
- **Right glass panel (330px):**
  - **Clips list:** each row has a numbered circle (white when selected), a quote or description, time, length and signal, plus a score pill (white if 80 or above, translucent otherwise).
  - **Segmented tabs:** Frame / Captions / Transcript / Thumbnail.
  - **Frame:** aspect ratio pills, plus a facecam switch with a note about the preset.
  - **Transcript:** word-timed lines, with low-confidence words wavy-underlined in amber.
  - **Thumbnail:** four suggested frames with a reason and a score; the selected one gets a white border. A note says a 1080×1920 vertical thumbnail with no text is also exported.
- **Timeline panel** (solid dark): a thumbnail strip, the waveform, and Part pills positioned at their times (the selected one is white).
- **Export dialog:**
  - Format radio cards: **Shorts package** (one folder per clip: `clip.mp4`, `transcript.srt`, `words.json`, `thumbs/`, `meta.json`) or **Video files only**.
  - A Save to path, then a progress bar ("Using the NVIDIA encoder, one clip at a time").
  - When done: a folder tree and **Open folder**.

### Settings (`Settings.dc.html`)
- Flex row with an 80/20 ratio: System check is `flex: 4 1 0; min-width: 520px`, and the side column is `flex: 1 1 0; min-width: 280px`. When the window is too narrow for both, the side column wraps below.
- **System check:**
  - Header with an "All good" or "Engine starting" badge and **Restart engine**.
  - A table with Component and Status columns: processing engine, database, FFmpeg, FFprobe, hardware encoding, speech recognition (CPU) and facecam detection.
  - While restarting: the engine shows "Starting…" and the others show red crosses.
  - Footer: the app version and Open logs folder.
- **Storage** (side column): for App data, Models and caches, and Exports, each row has the name and size on top, then a single line with a read-only path pill (ellipsis, full path on hover), a change-location icon button and a clear icon button.
  - Clear exists only for App data and Caches. It is a two-step confirm: the first click turns it red and shows a warning, and the second click clears.
  - Moving a location shows a note about what happens (models are moved rather than re-downloaded; earlier exports stay where they are).
- **Updates:** "Manual only. Nothing installs without asking you." plus Check now.

## 4. Component mapping

| Prototype element | shadcn/ui | Hugeicons (Stroke Rounded; closest match, verify the names) |
|---|---|---|
| Floating sidebar | Sidebar (floating variant) | Home, Settings, Scissor |
| Primary and secondary pills | Button (custom variants) | Add, Download, Upload |
| New project / Find clips / Export dialogs | Dialog | Cancel |
| Drop zone | custom component on top of Input file | Upload / Folder upload |
| Auto-clipping checkbox | Checkbox (circular style) | Tick |
| Option pills (kind, length, facecam, ratio) | Toggle Group | n/a |
| Editor tabs / view switch | Tabs (pill style) / Toggle Group | n/a |
| Facecam switch | Switch | n/a |
| Import, find and export progress | Progress | n/a |
| Status badges, score pills, chips | Badge | n/a |
| Clip list, video rows | Item / Scroll Area | n/a |
| System check table | Table | Checkmark circle / Cancel circle |
| Storage path | Input Group (read-only) + Button | Folder, Delete |
| Export format choice | Radio Group (card style) | n/a |
| Shortcuts | Kbd | Keyboard |

Before installing Hugeicons, check the license of the free set on their site.

## 5. Accessibility
- Every control is a real `button`, `a` or `input`; icon-only buttons have `aria-label`.
- Toggles use `role="radio"` or `role="switch"` with `aria-checked`, and tabs use `role="tab"` with `aria-selected`.
- Progress bars use `role="progressbar"`.
- Text contrast is at least 4.5:1.
- Touch targets are at least 34px in the dense editor and 40–44px elsewhere.

## 6. Placeholder content
Clip quotes, scores, transcripts, file names, paths, sizes and project names in the prototype are sample data. Video frames are grey blocks.
