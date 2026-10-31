"""Export queue: renders clips from the original sources to files in the user's chosen folder."""

import json
import logging
import re
import shutil
import sqlite3
import tempfile
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from . import clips, ffmpeg, sources
from .aspects import crop_path, crop_pixels, default_crop, output_size
from .captions.ass import build_ass
from .captions.cues import make_cues, to_srt
from .captions.service import clip_cues, clip_words, ensure_transcript
from .captions.styles import font_file
from .config import Settings
from .db import Database
from .edit.cutplan import TightenSettings
from .edit.service import plan_for_clip, tighten_settings
from .edit.timemap import TimeMap
from .events import EventHub
from .media import CancelToken, Cancelled, MediaError
from .media.probe import probe
from .media.render import (
    CPU_ENCODERS,
    FitOptions,
    build_video_filter,
    pick_encoder,
    pixel_format,
    render_clip,
    trim_window,
)
from .reframe.service import keyframes_cover, track_clip
from .reframe.track import crop_at

log = logging.getLogger("engine.exports")

ACTIVE_STATUSES = ("queued", "rendering")
FINISHED_STATUSES = ("done", "failed", "cancelled")
PROGRESS_INTERVAL_S = 0.4

_JOB_SELECT = """
    SELECT j.*, f.clip_id, f.aspect, f.mode, c.title AS clip_title, c.source_id, s.project_id
    FROM export_jobs j
    JOIN clip_formats f ON f.id = j.clip_format_id
    JOIN clips c ON c.id = f.clip_id
    JOIN sources s ON s.id = c.source_id
"""

_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def job_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "source_id": row["source_id"],
        "clip_id": row["clip_id"],
        "clip_title": row["clip_title"],
        "aspect": row["aspect"],
        "mode": row["mode"],
        "status": row["status"],
        "progress": row["progress"],
        "output_name": row["output_name"],
        "output_path": row["output_path"],
        "encoder": row["encoder"],
        "error": row["error"],
        "batch_id": row["batch_id"],
        "burn_captions": bool(row["burn_captions"]),
        "export_srt": bool(row["export_srt"]),
        "srt_path": row["srt_path"],
        "preset": json.loads(row["preset_json"]),
        "created_at": row["created_at"],
    }


def batch_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "zip": bool(row["zip"]),
        "zip_path": row["zip_path"],
        "error": row["error"],
        "created_at": row["created_at"],
    }


def get_job(conn: sqlite3.Connection, job_id: int) -> dict[str, Any] | None:
    row = conn.execute(_JOB_SELECT + " WHERE j.id = ?", (job_id,)).fetchone()
    return job_to_dict(row) if row else None


def list_jobs(conn: sqlite3.Connection, project_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(_JOB_SELECT + " WHERE s.project_id = ? ORDER BY j.id DESC", (project_id,)).fetchall()
    return [job_to_dict(r) for r in rows]


def active_job_ids(conn: sqlite3.Connection, *, clip_id=None, source_id=None, project_id=None) -> list[int]:
    """Running or queued exports of a clip, source or project, so deleting it can stop them first."""
    column, value = next((c, v) for c, v in (("c.id", clip_id), ("s.id", source_id), ("s.project_id", project_id)) if v is not None)
    placeholders = ",".join("?" * len(ACTIVE_STATUSES))
    rows = conn.execute(
        _JOB_SELECT + f" WHERE {column} = ? AND j.status IN ({placeholders})", (value, *ACTIVE_STATUSES)
    ).fetchall()
    return [r["id"] for r in rows]


def safe_filename(name: str, max_length: int = 120) -> str:
    name = _UNSAFE_CHARS.sub("", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:max_length].rstrip(" .") or "clip"


def render_name(template: str, **values: str) -> str:
    """Fill {project} {source} {title} {index} {ratio}; unknown placeholders are left as typed."""
    # Auto-generated titles end in "…" when shortened; that reads badly in a file name.
    values = {k: v.replace("…", "").strip() for k, v in values.items()}
    return safe_filename(re.sub(r"\{(\w+)\}", lambda m: values.get(m.group(1), m.group(0)), template))


def unique_path(folder: Path, stem: str, suffix: str = ".mp4") -> Path:
    candidate = folder / f"{stem}{suffix}"
    n = 2
    while candidate.exists():
        candidate = folder / f"{stem} ({n}){suffix}"
        n += 1
    return candidate


class ExportManager:
    def __init__(self, settings: Settings, db: Database, events: EventHub, max_workers: int = 2):
        self.settings = settings
        self.db = db
        self.events = events
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="export")
        self.tokens: dict[int, CancelToken] = {}
        self._zip_lock = threading.Lock()

    def start(self) -> None:
        placeholders = ",".join("?" * len(ACTIVE_STATUSES))
        with self.db.connect() as conn:
            conn.execute(
                f"UPDATE export_jobs SET status = 'failed', error = ? WHERE status IN ({placeholders})",
                ("Export was interrupted because the app closed", *ACTIVE_STATUSES),
            )

    def shutdown(self) -> None:
        for token in self.tokens.values():
            token.cancel()
        self.executor.shutdown(wait=False, cancel_futures=True)

    def submit(self, job: dict[str, Any]) -> None:
        token = CancelToken()
        self.tokens[job["id"]] = token
        self.events.emit("export", job)
        self.executor.submit(self._run, job["id"], token)

    def cancel(self, job_id: int) -> bool:
        token = self.tokens.get(job_id)
        if token is None:
            return False
        token.cancel()
        return True

    # --- worker side -------------------------------------------------------------------------

    def _update(self, job_id: int, **fields: Any) -> dict[str, Any] | None:
        assignments = ", ".join(f"{k} = ?" for k in fields)
        with self.db.connect() as conn:
            conn.execute(f"UPDATE export_jobs SET {assignments} WHERE id = ?", (*fields.values(), job_id))
            job = get_job(conn, job_id)
        if job:
            self.events.emit("export", job)
        return job

    def _track(self, row, token: CancelToken) -> list[dict]:
        """Run face tracking for a smart-framed export and save the path for the editor to show."""
        with self.db.connect() as conn:
            src = conn.execute("SELECT * FROM sources WHERE id = ?", (row["source_id"],)).fetchone()
        work_dir = sources.source_dir(self.settings, src["project_id"], src["id"])
        follow = json.loads(row["options_json"] or "{}").get("follow", "speaker")
        result = track_clip(self.settings, src, work_dir, row["start_ms"], row["end_ms"], row["aspect"], token, follow)
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE clip_formats SET crop_keyframes_json = ?, options_json = ? WHERE id = ?",
                (json.dumps(result.keyframes), json.dumps(result.options(follow)), row["format_id"]),
            )
            clip_id = conn.execute("SELECT clip_id FROM clip_formats WHERE id = ?", (row["format_id"],)).fetchone()[0]
            clip = clips.get(conn, clip_id)
        if clip:
            self.events.emit("clip", clip)
        return result.keyframes

    def _release(self, job_id: int, token: CancelToken) -> None:
        if self.tokens.get(job_id) is token:
            del self.tokens[job_id]

    def _run(self, job_id: int, token: CancelToken) -> None:
        with self.db.connect() as conn:
            row = conn.execute(
                """SELECT j.preset_json, j.output_name, j.batch_id, j.burn_captions, j.export_srt,
                          f.id AS format_id, f.aspect, f.mode, f.crop_keyframes_json, f.options_json,
                          c.id AS clip_id, c.start_ms, c.end_ms, s.id AS source_id, s.path, s.status AS source_status
                   FROM export_jobs j
                   JOIN clip_formats f ON f.id = j.clip_format_id
                   JOIN clips c ON c.id = f.clip_id
                   JOIN sources s ON s.id = c.source_id
                   WHERE j.id = ?""",
                (job_id,),
            ).fetchone()
        if row is None or token.cancelled:
            if row is not None:
                self._update(job_id, status="cancelled", error=None)
            self._release(job_id, token)
            return

        try:
            tools = ffmpeg.detect(self.settings.bin_dir)
            if not tools.ok:
                raise MediaError("FFmpeg was not found")
            src = Path(row["path"] or "")
            if row["source_status"] != "ready" or not src.is_file():
                raise MediaError(f"The original video is missing: {src}")

            self._update(job_id, status="rendering", progress=0, error=None)
            preset = json.loads(row["preset_json"])
            info = probe(tools.ffprobe.path, src)

            out_w, out_h = output_size(row["aspect"], int(preset["resolution"]))
            output_fps = info.fps_rational if preset["fps"] == "source" else str(preset["fps"])
            # Tighten: cut filler words and long pauses, then play the kept parts back to back.
            timemap = self._cut_plan(row, preset, token)
            keyframes = json.loads(row["crop_keyframes_json"])
            crop_px, path = None, None
            if row["mode"] == "smart":
                if not keyframes_cover(keyframes, row["start_ms"], row["end_ms"]):
                    # Never tracked, or the clip was extended past the tracked part: track now.
                    keyframes = self._track(row, token)
                if timemap:
                    # The joined segments start at output time 0, so the re-timed path needs no seek offset.
                    path = crop_path(timemap.map_keyframes(keyframes, crop_at), row["aspect"], info.width, info.height, 0.0)
                else:
                    seek, _ = trim_window(row["start_ms"], row["end_ms"], info.fps_rational)
                    path = crop_path(keyframes, row["aspect"], info.width, info.height, seek)
            elif row["mode"] != "fit":
                crop = keyframes[0] if keyframes else default_crop(row["aspect"], info.width, info.height)
                crop_px = crop_pixels(crop, row["aspect"], info.width, info.height)
            fit = FitOptions.from_dict(json.loads(row["options_json"] or "{}"))

            folder = Path(preset["output_dir"])
            folder.mkdir(parents=True, exist_ok=True)
            dest = unique_path(folder, row["output_name"])
            self._update(job_id, output_path=str(dest))

            cues, style, caption_offset = None, None, row["start_ms"]
            if row["burn_captions"] or row["export_srt"]:
                cues, style = self._captions(row, token, timemap)
                caption_offset = 0 if timemap else row["start_ms"]
            if row["burn_captions"] and cues:
                # libass reads the subtitles and font by relative name from a private folder, which
                # avoids escaping Windows paths inside the filter graph.
                caption_dir = Path(tempfile.mkdtemp(prefix="clipping-captions-"))
                (caption_dir / "captions.ass").write_text(
                    build_ass(cues, style, out_w, out_h, caption_offset), encoding="utf-8"
                )
                overlay = "subtitles=filename=captions.ass"
                if font := font_file(style.font):
                    (caption_dir / "fonts").mkdir()
                    shutil.copy(font, caption_dir / "fonts" / font.name)
                    overlay += ":fontsdir=fonts"
            else:
                caption_dir, overlay = None, ""

            encoder = pick_encoder(tools.ffmpeg.path, preset["codec"], preset["hardware"], tools.hw_encoders)
            last = {"t": 0.0}

            def on_progress(fraction: float) -> None:
                now = time.monotonic()
                if now - last["t"] >= PROGRESS_INTERVAL_S:
                    last["t"] = now
                    self._update(job_id, progress=round(fraction, 4))

            def render(enc: str) -> None:
                self._update(job_id, encoder=enc)
                render_clip(
                    tools.ffmpeg.path,
                    src,
                    dest,
                    start_ms=row["start_ms"],
                    end_ms=row["end_ms"],
                    source_fps=info.fps_rational,
                    output_fps=output_fps,
                    has_audio=info.has_audio,
                    video_filter=build_video_filter(
                        row["mode"], out_w, out_h, output_fps, crop_px, pixel_format(enc), path=path, fit=fit, overlay=overlay
                    ),
                    work_dir=caption_dir,
                    encoder=enc,
                    quality=preset["quality"],
                    cancel=token,
                    on_progress=on_progress,
                    segments=timemap.segments if timemap else None,
                )

            try:
                try:
                    render(encoder)
                except MediaError as err:
                    cpu = CPU_ENCODERS[preset["codec"]]
                    if encoder == cpu:
                        raise
                    # GPU encoders can fail on unusual sizes or busy hardware; the CPU always works.
                    log.warning("Export %s failed on %s, retrying on CPU: %s", job_id, encoder, err)
                    render(cpu)
            finally:
                if caption_dir:
                    shutil.rmtree(caption_dir, ignore_errors=True)

            if row["export_srt"] and cues:
                srt = dest.with_suffix(".srt")
                srt.write_text(to_srt(cues, style, caption_offset), encoding="utf-8")
                self._update(job_id, srt_path=str(srt))
            self._update(job_id, status="done", progress=1, error=None)
        except Cancelled:
            self._update(job_id, status="cancelled", error=None)
        except MediaError as err:
            self._update(job_id, status="failed", error=str(err))
        except Exception as err:
            log.exception("Export %s failed", job_id)
            self._update(job_id, status="failed", error=f"Unexpected error: {err}")
        finally:
            self._release(job_id, token)
            if row["batch_id"]:
                self._finish_batch(row["batch_id"])

    def _cut_plan(self, row, preset: dict, token: CancelToken) -> TimeMap | None:
        """The kept segments when the clip is tightened (its own setting, or "tighten all" on export)."""
        with self.db.connect() as conn:
            clip = conn.execute("SELECT * FROM clips WHERE id = ?", (row["clip_id"],)).fetchone()
            src = conn.execute("SELECT * FROM sources WHERE id = ?", (row["source_id"],)).fetchone()
        tighten = tighten_settings(clip)
        if tighten is None and preset.get("tighten_all"):
            tighten = TightenSettings()
        if tighten is None:
            return None
        plan = plan_for_clip(self.settings, clip, src, tighten, token, transcribe_if_needed=True)
        return TimeMap(plan.segments) if plan and len(plan.segments) > 1 else None

    def _captions(self, row, token: CancelToken, timemap: TimeMap | None = None):
        """Cues and style for a job's clip, transcribing the source first if it never was.

        For a tightened clip the words are re-timed onto the shortened clip (removed words drop out).
        """
        with self.db.connect() as conn:
            clip = conn.execute("SELECT * FROM clips WHERE id = ?", (row["clip_id"],)).fetchone()
            src = conn.execute("SELECT * FROM sources WHERE id = ?", (row["source_id"],)).fetchone()
            cues, _, style = clip_cues(conn, self.settings, clip)
        if cues is None:
            ensure_transcript(self.settings, src, token)
            with self.db.connect() as conn:
                cues, _, style = clip_cues(conn, self.settings, clip)
        if timemap and cues:
            with self.db.connect() as conn:
                words, _ = clip_words(conn, self.settings, clip)
            cues = make_cues(timemap.map_words(words or []), style, end_limit=round(timemap.duration))
        return cues or [], style

    def _finish_batch(self, batch_id: str) -> None:
        """When every job in a ZIP batch has finished, bundle the finished videos and .srt files."""
        with self._zip_lock, self.db.connect() as conn:
            batch = conn.execute("SELECT * FROM export_batches WHERE id = ?", (batch_id,)).fetchone()
            if batch is None or not batch["zip"] or batch["zip_path"]:
                return
            jobs = conn.execute(
                "SELECT status, output_path, srt_path, preset_json FROM export_jobs WHERE batch_id = ?", (batch_id,)
            ).fetchall()
            if any(j["status"] in ACTIVE_STATUSES for j in jobs):
                return
            files = [Path(p) for j in jobs if j["status"] == "done" for p in (j["output_path"], j["srt_path"]) if p]
            files = [f for f in files if f.is_file()]
            if not files:
                conn.execute("UPDATE export_batches SET error = ? WHERE id = ?", ("No videos finished", batch_id))
            else:
                project = conn.execute("SELECT name FROM projects WHERE id = ?", (batch["project_id"],)).fetchone()
                folder = Path(json.loads(jobs[0]["preset_json"])["output_dir"])
                target = unique_path(folder, safe_filename(f"{project['name']} clips"), ".zip")
                try:
                    tmp = target.with_suffix(".partial.zip")
                    # Videos are already compressed; storing them is as small and much faster.
                    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as zf:
                        for f in files:
                            zf.write(f, f.name)
                    tmp.replace(target)
                    conn.execute("UPDATE export_batches SET zip_path = ? WHERE id = ?", (str(target), batch_id))
                except OSError as err:
                    conn.execute("UPDATE export_batches SET error = ? WHERE id = ?", (f"Could not create the ZIP: {err}", batch_id))
            updated = conn.execute("SELECT * FROM export_batches WHERE id = ?", (batch_id,)).fetchone()
        self.events.emit("export_batch", batch_to_dict(updated))
