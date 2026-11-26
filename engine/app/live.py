"""Recording live streams from a link, with a preview the app can play while it records.

Each recording runs in its own thread. It finds the stream, records it with FFmpeg (copying it as broadcast),
reconnects if the connection drops, and when the stream ends or the user stops it, joins the pieces into one
MP4 in the user's recordings folder and imports it into the chosen project like any other video.

If the app closes mid-recording, the pieces stay in the work folder and show up as "interrupted" on the next
start, so they can still be saved.
"""

import json
import logging
import shutil
import subprocess
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any

from . import clips, ffmpeg, sources
from .config import Settings
from .db import Database
from .events import EventHub
from .ingest import IngestManager
from .media import MediaError
from .media import live as live_media

log = logging.getLogger("engine.live")

ACTIVE = ("starting", "recording", "reconnecting", "finishing")
MIN_FREE_TO_START = 5 * 1024**3  # bytes free on the recordings drive before a recording may start
MIN_FREE_WHILE_RECORDING = 1536 * 1024**2  # stop cleanly below this, before the disk is full
STALL_S = 30  # no new data for this long counts as a dropped connection
STOP_GRACE_S = 15  # how long FFmpeg gets to finish writing after "q"
EMIT_INTERVAL_S = 2.0
MAX_RECONNECTS = 12  # failed reconnects in a row before giving up (about 6 minutes with the backoff)
MARK_BEFORE_MS = 30_000  # a marked moment becomes a clip from 30 s before the mark...
MARK_AFTER_MS = 5_000  # ...to 5 s after it (the preview runs a few seconds behind live)
MARK_WAIT_S = 12 * 3600  # give the import this long to finish before dropping marked moments


class _Recording:
    def __init__(self, rec_id: int, url: str, project_id: int, quality: str, output_dir: Path, work: Path):
        self.id = rec_id
        self.url = url
        self.project_id = project_id
        self.quality = quality
        self.output_dir = output_dir
        self.work = work
        self.status = "starting"
        self.title: str | None = None
        self.channel: str | None = None
        self.started_at = datetime.now().astimezone()
        self.elapsed_ms = 0
        self.size_bytes = 0
        self.free_bytes: int | None = None
        self.part = 0
        self.parts: list[Path] = []
        self.marks: list[int] = []
        self.source_id: int | None = None
        self.output_path: str | None = None
        self.error: str | None = None
        self.note: str | None = None
        self.vcodec: str | None = None
        self.stop = threading.Event()
        self.discard = False
        self.process: subprocess.Popen | None = None
        self.thread: threading.Thread | None = None

    def to_dict(self) -> dict[str, Any]:
        live = self.status in ("recording",) and self.part > 0
        return {
            "id": self.id,
            "url": self.url,
            "project_id": self.project_id,
            "quality": self.quality,
            "output_dir": str(self.output_dir),
            "status": self.status,
            "title": self.title,
            "channel": self.channel,
            "started_at": self.started_at.isoformat(timespec="seconds"),
            "elapsed_ms": self.elapsed_ms,
            "size_bytes": self.size_bytes,
            "free_bytes": self.free_bytes,
            "part": self.part,
            "marks": list(self.marks),
            "source_id": self.source_id,
            "output_path": self.output_path,
            "error": self.error,
            "note": self.note,
            "vcodec": self.vcodec,
            # Fetched by the app's player; the client appends its token.
            "preview_url": f"/media/live/{self.id}/{self.part}/{live_media.PREVIEW_PLAYLIST}" if live else None,
        }

    def save_state(self) -> None:
        state = {
            "url": self.url,
            "project_id": self.project_id,
            "quality": self.quality,
            "output_dir": str(self.output_dir),
            "title": self.title,
            "channel": self.channel,
            "started_at": self.started_at.isoformat(timespec="seconds"),
            "elapsed_ms": self.elapsed_ms,
            "marks": self.marks,
        }
        try:
            (self.work / "state.json").write_text(json.dumps(state), encoding="utf-8")
        except OSError:
            log.warning("Couldn't save state for recording %s", self.id)


class LiveManager:
    def __init__(self, settings: Settings, db: Database, events: EventHub, ingest: IngestManager):
        self.settings = settings
        self.db = db
        self.events = events
        self.ingest = ingest
        self.root = settings.work_dir / "live"
        self.recordings: dict[int, _Recording] = {}
        self._lock = threading.Lock()
        self._next_id = 1
        self._shutting_down = False

    # --- lifecycle ---------------------------------------------------------------------------

    def start(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        for folder in sorted(self.root.iterdir(), key=lambda p: p.name):
            if not (folder.is_dir() and folder.name.isdigit()):
                continue
            rec_id = int(folder.name)
            self._next_id = max(self._next_id, rec_id + 1)
            rec = self._recover(rec_id, folder)
            if rec is None:
                shutil.rmtree(folder, ignore_errors=True)
            else:
                self.recordings[rec_id] = rec

    def shutdown(self) -> None:
        # The pieces recorded so far stay in the work folder and are offered as "interrupted" next time.
        self._shutting_down = True
        for rec in list(self.recordings.values()):
            if rec.status in ACTIVE:
                rec.stop.set()
                if rec.process and rec.process.poll() is None:
                    rec.process.kill()

    def _recover(self, rec_id: int, folder: Path) -> "_Recording | None":
        parts = sorted(p for p in folder.glob("part*.ts") if p.stat().st_size > 0)
        try:
            state = json.loads((folder / "state.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            state = None
        if not parts or not state:
            return None
        rec = _Recording(rec_id, state["url"], state["project_id"], state.get("quality", "source"), Path(state["output_dir"]), folder)
        rec.status = "interrupted"
        rec.title = state.get("title")
        rec.channel = state.get("channel")
        rec.elapsed_ms = int(state.get("elapsed_ms") or 0)
        rec.marks = [int(m) for m in state.get("marks") or []]
        rec.parts = parts
        rec.size_bytes = sum(p.stat().st_size for p in parts)
        rec.note = "The app closed while this was recording. Save what was recorded, or discard it."
        try:
            rec.started_at = datetime.fromisoformat(state["started_at"])
        except (KeyError, ValueError):
            pass
        return rec

    # --- requests ----------------------------------------------------------------------------

    def all(self) -> list[dict[str, Any]]:
        with self._lock:
            return [r.to_dict() for r in sorted(self.recordings.values(), key=lambda r: -r.id)]

    def get(self, rec_id: int) -> _Recording | None:
        return self.recordings.get(rec_id)

    def begin(self, url: str, project_id: int, quality: str, output_dir: Path) -> dict[str, Any]:
        if quality not in live_media.QUALITIES:
            raise MediaError("Unknown quality")
        tools = ffmpeg.detect(self.settings.bin_dir)
        if not tools.ok:
            raise MediaError('FFmpeg was not found. Run "npm run bundle:ffmpeg" and restart the engine.')
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as err:
            raise MediaError(f"Couldn't create the recordings folder: {err}") from err
        free = shutil.disk_usage(output_dir).free
        if free < MIN_FREE_TO_START:
            raise MediaError(f"Only {free / 1024**3:.1f} GB is free on that drive. Free up at least 5 GB before recording.")
        with self._lock:
            if any(r.url == url and r.status in ACTIVE for r in self.recordings.values()):
                raise MediaError("This stream is already being recorded.")
            rec_id = self._next_id
            self._next_id += 1
            work = self.root / str(rec_id)
            shutil.rmtree(work, ignore_errors=True)
            work.mkdir(parents=True)
            rec = _Recording(rec_id, url, project_id, quality, output_dir, work)
            rec.free_bytes = free
            self.recordings[rec_id] = rec
        rec.save_state()
        rec.thread = threading.Thread(target=self._run, args=(rec,), name=f"live-{rec_id}", daemon=True)
        rec.thread.start()
        self._emit(rec)
        return rec.to_dict()

    def stop(self, rec_id: int) -> dict[str, Any] | None:
        rec = self.recordings.get(rec_id)
        if rec is None:
            return None
        rec.stop.set()
        self._ask_ffmpeg_to_stop(rec)
        return rec.to_dict()

    def save_interrupted(self, rec_id: int) -> dict[str, Any] | None:
        rec = self.recordings.get(rec_id)
        if rec is None or rec.status != "interrupted":
            return None
        rec.status = "finishing"
        rec.note = None
        rec.thread = threading.Thread(target=self._finish_thread, args=(rec,), name=f"live-{rec_id}-save", daemon=True)
        rec.thread.start()
        self._emit(rec)
        return rec.to_dict()

    def discard(self, rec_id: int) -> bool:
        """Stop without saving (if running) and forget it. A saved recording's file is never deleted."""
        rec = self.recordings.get(rec_id)
        if rec is None:
            return False
        if rec.status in ("starting", "recording", "reconnecting"):
            rec.discard = True
            rec.stop.set()
            self._ask_ffmpeg_to_stop(rec)
            return True  # the thread removes the files and announces it
        if rec.status == "finishing":
            raise MediaError("This recording is being saved. Wait for it to finish, then remove it.")
        with self._lock:
            self.recordings.pop(rec_id, None)
        shutil.rmtree(rec.work, ignore_errors=True)
        self.events.emit("recording_removed", {"id": rec_id})
        return True

    def mark(self, rec_id: int) -> dict[str, Any] | None:
        rec = self.recordings.get(rec_id)
        if rec is None or rec.status not in ("recording", "reconnecting"):
            return None
        rec.marks.append(rec.elapsed_ms)
        rec.save_state()
        self._emit(rec)
        return rec.to_dict()

    def preview_file(self, rec_id: int, part: int, name: str) -> Path | None:
        rec = self.recordings.get(rec_id)
        if rec is None or not live_media.PREVIEW_FILE_RE.match(name):
            return None
        path = rec.work / "preview" / str(part) / name
        return path if path.is_file() else None

    # --- worker side -------------------------------------------------------------------------

    def _emit(self, rec: _Recording) -> None:
        self.events.emit("recording", rec.to_dict())

    def _ask_ffmpeg_to_stop(self, rec: _Recording) -> None:
        proc = rec.process
        if proc and proc.poll() is None and proc.stdin:
            try:
                proc.stdin.write(b"q")
                proc.stdin.flush()
            except OSError:
                pass

    def _run(self, rec: _Recording) -> None:
        try:
            self._record(rec)
            if self._shutting_down and not rec.discard:
                rec.save_state()  # left for the next start to offer as interrupted
                return
            if rec.discard:
                self._forget(rec)
                return
            if not rec.parts:
                rec.status = "failed" if rec.error else "cancelled"
                self._emit(rec)
                shutil.rmtree(rec.work, ignore_errors=True)
                return
            rec.status = "finishing"
            self._emit(rec)
            self._finish(rec)
        except Exception as err:
            log.exception("Recording %s failed", rec.id)
            rec.status = "failed"
            rec.error = f"Unexpected error: {err}"
            self._emit(rec)

    def _forget(self, rec: _Recording) -> None:
        with self._lock:
            self.recordings.pop(rec.id, None)
        shutil.rmtree(rec.work, ignore_errors=True)
        self.events.emit("recording_removed", {"id": rec.id})

    def _record(self, rec: _Recording) -> None:
        tools = ffmpeg.detect(self.settings.bin_dir)
        failures = 0
        first = True
        while not rec.stop.is_set():
            rec.status = "starting" if first else "reconnecting"
            self._emit(rec)
            try:
                stream = live_media.resolve(rec.url, rec.quality)
            except MediaError as err:
                if first:
                    rec.error = str(err)
                    return
                if "isn't live" in str(err):
                    rec.note = "The stream ended."
                    return
                failures += 1
                if failures > MAX_RECONNECTS:
                    rec.note = "Stopped after the connection kept failing."
                    return
                rec.stop.wait(min(30, 3 * failures))
                continue

            if rec.stop.is_set():
                return
            first = False
            rec.title = rec.title or stream.title
            rec.channel = rec.channel or stream.channel
            rec.vcodec = stream.vcodec
            rec.save_state()

            got_data = self._record_part(rec, tools.ffmpeg.path, stream)
            if got_data:
                failures = 0
            else:
                failures += 1
                if failures > MAX_RECONNECTS:
                    rec.note = "Stopped after the connection kept failing."
                    return
                rec.stop.wait(min(30, 3 * failures))

    def _record_part(self, rec: _Recording, ffmpeg_path: str, stream: live_media.LiveStream) -> bool:
        """Record until FFmpeg exits, the connection stalls or the user stops. True if anything was written."""
        index = len(rec.parts) + 1
        part = rec.work / f"part{index:03d}.ts"
        preview = rec.work / "preview" / str(index)
        preview.mkdir(parents=True, exist_ok=True)
        command = live_media.record_command(ffmpeg_path, stream, part, preview)
        proc = subprocess.Popen(
            command,
            cwd=preview,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=ffmpeg.NO_WINDOW,
        )
        rec.process = proc
        errors: deque[str] = deque(maxlen=20)

        def drain() -> None:
            for line in iter(proc.stderr.readline, b""):
                errors.append(line.decode("utf-8", "replace").rstrip())

        threading.Thread(target=drain, daemon=True).start()

        base_elapsed = rec.elapsed_ms
        base_size = sum(p.stat().st_size for p in rec.parts if p.exists())
        data_started: float | None = None
        last_size = 0
        last_growth = time.monotonic()
        last_emit = 0.0
        stop_sent: float | None = None

        while proc.poll() is None:
            time.sleep(0.5)
            now = time.monotonic()
            size = part.stat().st_size if part.exists() else 0
            if size > last_size:
                last_size = size
                last_growth = now
                if data_started is None:
                    data_started = now
                    rec.parts.append(part)
                    rec.part = index
                    rec.status = "recording"
                    self._remove_old_previews(rec, index)
            if data_started is not None:
                rec.elapsed_ms = base_elapsed + int((now - data_started) * 1000)
            rec.size_bytes = base_size + size

            if rec.stop.is_set():
                if stop_sent is None:
                    stop_sent = now
                    self._ask_ffmpeg_to_stop(rec)
                elif now - stop_sent > STOP_GRACE_S:
                    proc.kill()
            elif now - last_growth > STALL_S:
                log.info("Recording %s stalled; reconnecting", rec.id)
                proc.kill()

            if now - last_emit >= EMIT_INTERVAL_S:
                last_emit = now
                try:
                    rec.free_bytes = shutil.disk_usage(rec.output_dir).free
                except OSError:
                    rec.free_bytes = None
                if rec.free_bytes is not None and rec.free_bytes < MIN_FREE_WHILE_RECORDING and not rec.stop.is_set():
                    rec.note = "Stopped because the disk is almost full."
                    rec.stop.set()
                self._emit(rec)
                if int(now) % 30 < EMIT_INTERVAL_S:
                    rec.save_state()

        rec.process = None
        if errors and not rec.stop.is_set():
            log.info("Recording %s connection ended: %s", rec.id, errors[-1])
        if data_started is None:
            part.unlink(missing_ok=True)
            return False
        rec.save_state()
        return True

    def _remove_old_previews(self, rec: _Recording, current: int) -> None:
        root = rec.work / "preview"
        for folder in root.iterdir() if root.exists() else []:
            if folder.name != str(current):
                shutil.rmtree(folder, ignore_errors=True)

    def _finish_thread(self, rec: _Recording) -> None:
        try:
            self._finish(rec)
        except Exception as err:
            log.exception("Saving recording %s failed", rec.id)
            rec.status = "failed"
            rec.error = f"Unexpected error: {err}"
            self._emit(rec)

    def _finish(self, rec: _Recording) -> None:
        """Join the parts into one MP4 in the recordings folder, then import it into the project."""
        tools = ffmpeg.detect(self.settings.bin_dir)
        shutil.rmtree(rec.work / "preview", ignore_errors=True)
        parts = [p for p in rec.parts if p.exists() and p.stat().st_size > 0]
        if not parts:
            rec.status = "failed"
            rec.error = "Nothing was recorded."
            self._emit(rec)
            return

        rec.output_dir.mkdir(parents=True, exist_ok=True)
        output = _unique(rec.output_dir / live_media.recording_name(rec.channel, rec.started_at.strftime("%Y-%m-%d %H-%M")))
        list_file = rec.work / "parts.txt"
        list_file.write_text(live_media.concat_list(parts), encoding="utf-8")
        command = live_media.finish_command(tools.ffmpeg.path, parts, list_file, output)
        result = subprocess.run(command, capture_output=True, creationflags=ffmpeg.NO_WINDOW)
        if result.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
            output.unlink(missing_ok=True)
            if len(parts) == 1:
                # Keep the recording as it was captured; it imports just the same.
                output = _unique(output.with_suffix(".ts"))
                shutil.move(str(parts[0]), output)
            else:
                rec.status = "interrupted"
                rec.note = None
                rec.error = "Couldn't join the recorded pieces. Try Save again, or find them in the app's work folder."
                log.warning("Joining recording %s failed: %s", rec.id, result.stderr.decode("utf-8", "replace")[-500:])
                self._emit(rec)
                return

        rec.output_path = str(output)
        shutil.rmtree(rec.work, ignore_errors=True)

        source = self._import(rec, output)
        if source is None:
            rec.note = f"Saved to {output}. The project no longer exists, so it wasn't imported."
        else:
            rec.source_id = source["id"]
            if rec.marks:
                threading.Thread(target=self._clips_from_marks, args=(source["id"], list(rec.marks)), daemon=True).start()
        rec.status = "done"
        rec.error = None
        self._emit(rec)

    def _import(self, rec: _Recording, path: Path) -> dict[str, Any] | None:
        title = rec.title or path.stem
        with self.db.connect() as conn:
            if not conn.execute("SELECT 1 FROM projects WHERE id = ?", (rec.project_id,)).fetchone():
                return None
            cur = conn.execute(
                "INSERT INTO sources (project_id, origin, url, path, title, status) VALUES (?, 'file', NULL, ?, ?, 'queued')",
                (rec.project_id, str(path.resolve()), title[:200]),
            )
            conn.execute("UPDATE projects SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?", (rec.project_id,))
            source = sources.get(conn, cur.lastrowid)
        self.ingest.remove_files(self.ingest.source_dir(rec.project_id, source["id"]))
        self.ingest.submit(source)
        return source

    def _clips_from_marks(self, source_id: int, marks: list[int]) -> None:
        """Once the recording has imported, turn each marked moment into a clip."""
        deadline = time.monotonic() + MARK_WAIT_S
        while time.monotonic() < deadline:
            with self.db.connect() as conn:
                row = conn.execute("SELECT status, duration_ms FROM sources WHERE id = ?", (source_id,)).fetchone()
            if row is None or row["status"] in ("failed", "cancelled"):
                return
            if row["status"] == "ready" and row["duration_ms"]:
                break
            time.sleep(3)
        else:
            return

        duration = row["duration_ms"]
        ranges: list[list[int]] = []
        for mark in sorted(marks):
            start, end = max(0, mark - MARK_BEFORE_MS), min(duration, mark + MARK_AFTER_MS)
            if end - start < 1000:
                continue
            if ranges and start <= ranges[-1][1]:
                ranges[-1][1] = max(ranges[-1][1], end)  # overlapping marks become one clip
            else:
                ranges.append([start, end])

        with self.db.connect() as conn:
            count = conn.execute("SELECT COUNT(*) FROM clips WHERE source_id = ?", (source_id,)).fetchone()[0]
            created = []
            for n, (start, end) in enumerate(ranges, 1):
                cur = conn.execute(
                    """INSERT INTO clips (source_id, start_ms, end_ms, title, status, sort_order, created_at)
                       VALUES (?, ?, ?, ?, 'kept', ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))""",
                    (source_id, start, end, f"Marked moment {n}", count + n - 1),
                )
                created.append(clips.get(conn, cur.lastrowid))
        for clip in created:
            self.events.emit("clip", clip)


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    for n in range(2, 1000):
        candidate = path.with_name(f"{path.stem} ({n}){path.suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{path.stem} {int(time.time())}{path.suffix}")
