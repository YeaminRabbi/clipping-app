# Live stream recording (26 Nov 2026)

A **Live** screen (radio icon in the sidebar) records Twitch and YouTube live streams from a link, with a player so you can watch while it records.

## How it works
- **Finding the stream:** the engine uses yt-dlp, already used by Import link, to find the stream behind the link. It prefers H.264 HLS, so the in-app player can show it.
- **One download, two outputs:** a single FFmpeg process copies the stream without re-encoding into:
  - `part001.ts` and so on: the recording, in a format that survives crashes
  - a rolling preview (2-second fragmented MP4 pieces) that the app's player reads from `/media/live/...`.

  Almost no CPU or GPU is used.
- **Reconnects:** if the connection drops or stalls for 30 s, the engine reconnects into a new part. It gives up after 12 failed tries in a row.
- **The end:** when the stream ends or you press Stop and save, the parts are joined into one MP4 (no re-encode) in `<exports location>/Recordings` and imported into the chosen project. If "Find clips when the stream ends" is ticked, Find clips runs after the import, using your last Find clips settings.
- **Mark moment** (button or the M key): each mark becomes a clip from 30 s before to 5 s after the mark, because the preview runs a few seconds behind live. Overlapping marks merge into one clip.
- **App closed mid-recording:** the parts stay in the engine's work folder and appear as "Interrupted" next time, with Save and Discard.
- **Disk space:** a recording won't start with under 5 GB free, and stops cleanly below 1.5 GB.

## Files
- Engine: `app/media/live.py` (finding the stream, FFmpeg commands), `app/live.py` (the recorder), `app/api/live.py` (endpoints), `tests/test_live.py`
- App: `components/live/LiveView.tsx`, `components/live/LivePlayer.tsx` (a MediaSource player, no new package), plus the store, API client and sidebar

## Known limits
- **Twitch ads:** on channels you're not subscribed to, Twitch can insert ads or a "commercial break" screen into the stream, and they get recorded too.
- **YouTube:** recent yt-dlp versions may need a JavaScript runtime (such as Deno) installed for some YouTube formats. If YouTube links fail while Twitch works, that's the likely cause.
- **Preview formats:** the preview shows H.264 streams only. HEVC and AV1 streams still record, but the player shows a note instead of video.
- **Session-only:** the "find clips when it ends" choice applies to recordings started in this session.
