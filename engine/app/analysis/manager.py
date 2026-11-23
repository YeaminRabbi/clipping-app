"""Background analysis job: transcribe, measure, score, and replace a source's suggested clips."""

import json
import logging
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from pathlib import Path
from typing import Any

from .. import clips, exports, ffmpeg, sources
from ..captions.service import save_transcript, transcript_lock
from ..config import Settings
from ..db import Database
from ..events import EventHub
from ..media import CancelToken, Cancelled, MediaError
from .finder import FindSettings, find_clips
from .scoring import Signals
from .signals import cached_scene_cuts, loudness, silences
from .transcribe import load_cached, model_is_downloaded, transcribe, transcribing_stage

log = logging.getLogger("engine.analysis")

ACTIVE_STATUSES = ("queued", "running")
PROGRESS_INTERVAL_S = 0.4


def to_dict(row) -> dict[str, Any]:
    result = json.loads(row["result_json"]) if row["result_json"] else {}
    return {
        "source_id": row["source_id"],
        "status": row["status"],
        "stage": row["stage"],
        "progress": row["progress"],
        "error": row["error"],
        "settings": json.loads(row["settings_json"]),
        "notes": result.get("notes", []),
        "mode_used": result.get("mode_used"),
        "clip_count": result.get("clip_count"),
        "updated_at": row["updated_at"],
        # find_clips | transcribe. Settings stay those of the last clip-finding run either way.
        "task": row["task"],
    }


def get(conn, source_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM analyses WHERE source_id = ?", (source_id,)).fetchone()
    return to_dict(row) if row else None


class AlreadyRunning(Exception):
    """An analysis of this video is already queued or running."""


class AnalysisManager:
    def __init__(self, settings: Settings, db: Database, events: EventHub, export_manager: "exports.ExportManager"):
        self.settings = settings
        self.db = db
        self.events = events
        # Replacing suggested clips must stop their exports first (see exports.delete_clips).
        self.export_manager = export_manager
        # Transcription uses every core; one analysis at a time keeps the app responsive.
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="analysis")
        self.tokens: dict[int, CancelToken] = {}
        # Makes "is one running? if not, start one" a single step for concurrent requests.
        self._submit_lock = threading.Lock()

    def start(self) -> None:
        with self.db.connect() as conn:
            conn.execute(
                "UPDATE analyses SET status = 'failed', error = ? WHERE status IN ('queued', 'running')",
                ("Analysis was interrupted because the app closed",),
            )

    def shutdown(self) -> None:
        for token in self.tokens.values():
            token.cancel()
        self.executor.shutdown(wait=False, cancel_futures=True)

    def submit(self, source_id: int, params: dict[str, Any]) -> dict[str, Any]:
        """Queue an analysis. Mode "transcribe" only transcribes (for captions) and keeps the previous
        clip-finding results, so "Replace this clip" still works afterwards."""
        transcribe_only = params["mode"] == "transcribe"
        token = CancelToken()
        with self._submit_lock:
            if source_id in self.tokens:
                raise AlreadyRunning()
            self.tokens[source_id] = token
        try:
            analysis = self._queue_row(source_id, params, transcribe_only)
            # Announce "queued" before the worker can start and announce "running".
            self.events.emit("analysis", analysis)
            # Fails once the engine is shutting down; the token must not outlive the request then.
            self.executor.submit(self._run, source_id, params, token)
        except BaseException:
            self.tokens.pop(source_id, None)
            raise
        return analysis

    def _queue_row(self, source_id: int, params: dict[str, Any], transcribe_only: bool) -> dict[str, Any]:
        with self.db.connect() as conn:
            conn.execute(
                f"""INSERT INTO analyses (source_id, status, stage, progress, settings_json, result_json, error, task)
                   VALUES (?, 'queued', 'Waiting to start', 0, ?, NULL, NULL, ?)
                   ON CONFLICT (source_id) DO UPDATE SET status = 'queued', stage = 'Waiting to start', progress = 0,
                     error = NULL, task = excluded.task, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                     {"" if transcribe_only else ", settings_json = excluded.settings_json, result_json = NULL"}""",
                (source_id, json.dumps({} if transcribe_only else params), "transcribe" if transcribe_only else "find_clips"),
            )
            return get(conn, source_id)

    def cancel(self, source_id: int) -> bool:
        token = self.tokens.get(source_id)
        if token is None:
            return False
        token.cancel()
        return True

    # --- worker side -------------------------------------------------------------------------

    def _update(self, source_id: int, token: CancelToken, **fields: Any) -> None:
        if self.tokens.get(source_id) is not token:  # not this job's row any more (see IngestManager._update)
            return
        assignments = ", ".join(f"{k} = ?" for k in fields)
        with self.db.connect() as conn:
            conn.execute(
                f"UPDATE analyses SET {assignments}, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE source_id = ?",
                (*fields.values(), source_id),
            )
            analysis = get(conn, source_id)
        if analysis:
            self.events.emit("analysis", analysis)

    def _reporter(self, source_id: int, token: CancelToken, start: float, span: float):
        last = {"t": 0.0}

        def report(fraction: float) -> None:
            now = time.monotonic()
            if now - last["t"] >= PROGRESS_INTERVAL_S:
                last["t"] = now
                with suppress(sqlite3.OperationalError):  # database busy: the next update will do
                    self._update(source_id, token, progress=round(start + span * fraction, 4))

        return report

    def _run(self, source_id: int, params: dict[str, Any], token: CancelToken) -> None:
        try:
            with self.db.connect() as conn:
                src = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
            if src is None:
                return
            token.raise_if_cancelled()
            if src["status"] != "ready":
                raise MediaError("This video is still importing")
            tools = ffmpeg.detect(self.settings.bin_dir)
            work_dir = sources.source_dir(self.settings, src["project_id"], source_id)
            proxy = Path(src["proxy_path"] or "")
            duration = src["duration_ms"]
            self._update(source_id, token, status="running", progress=0, error=None)

            mode = params["mode"]
            if mode == "transcribe":
                if not src["has_audio"]:
                    raise MediaError("This video has no sound to transcribe")
                self._transcript(source_id, src, proxy, work_dir, params, token)
                self._update(source_id, token, status="done", stage=None, progress=1, error=None)
                self.events.emit("transcript", {"source_id": source_id})
                return
            needs_speech = mode == "talking" or (mode == "action" and params["keywords"])
            words: list[dict] = []
            done = 0.0
            if needs_speech and src["has_audio"]:
                words = self._transcript(source_id, src, proxy, work_dir, params, token)
                done = 0.8

            self._update(source_id, token, stage="Finding scene changes", progress=done)
            cuts = self._scene_cuts(source_id, proxy, work_dir, duration, token, done, 0.95 - done)
            token.raise_if_cancelled()
            self._update(source_id, token, stage="Measuring audio", progress=0.95)
            levels = loudness(tools.ffmpeg.path, proxy, duration, bool(src["has_audio"]))
            sig = Signals(words=words, loudness=levels, cuts=cuts, silences=silences(levels))

            token.raise_if_cancelled()
            self._update(source_id, token, stage="Scoring moments", progress=0.97)
            lo = max(0, params.get("range_start_ms") or 0)
            hi = min(duration, params.get("range_end_ms") or duration)
            settings = FindSettings(
                mode=mode,
                count=params.get("clip_count"),
                min_ms=round(params["min_seconds"] * 1000),
                max_ms=round(params["max_seconds"] * 1000),
                lo=lo,
                hi=hi,
                keywords=params.get("keywords") or [],
            )
            self._apply(source_id, settings, sig, duration, token)
        except Cancelled:
            self._update(source_id, token, status="cancelled", stage=None, error=None)
        except MediaError as err:
            self._update(source_id, token, status="failed", stage=None, error=str(err))
        except Exception as err:
            log.exception("Analysis failed for source %s", source_id)
            self._update(source_id, token, status="failed", stage=None, error=f"Unexpected error: {err}")
        finally:
            if self.tokens.get(source_id) is token:
                del self.tokens[source_id]

    def _transcript(self, source_id, src, proxy: Path, work_dir: Path, params, token) -> list[dict]:
        # An export that needs captions may be transcribing this video right now; wait and reuse it.
        with transcript_lock(source_id):
            return self._transcript_locked(source_id, src, proxy, work_dir, params, token)

    def _transcript_locked(self, source_id, src, proxy: Path, work_dir: Path, params, token) -> list[dict]:
        path = work_dir / "transcript.json"
        model, language = params.get("model", "base"), params.get("language")
        cached = load_cached(path, model, language)
        if cached:
            return cached["words"]
        if not model_is_downloaded(self.settings.models_path, model):
            self._update(source_id, token, stage="Downloading speech model (first time only)")
        else:
            self._update(source_id, token, stage=transcribing_stage())
        tools = ffmpeg.detect(self.settings.bin_dir)
        first = {"seen": False}
        report = self._reporter(source_id, token, 0, 0.8)

        def on_progress(fraction: float) -> None:
            if not first["seen"]:
                first["seen"] = True
                self._update(source_id, token, stage=transcribing_stage())
            report(fraction)

        data = transcribe(
            tools.ffmpeg.path, proxy, src["duration_ms"], self.settings.models_path, model, language, token, on_progress
        )
        save_transcript(self.settings, src, data)
        return data["words"]

    def _scene_cuts(self, source_id, proxy: Path, work_dir: Path, duration: int, token, start: float, span: float) -> list[int]:
        tools = ffmpeg.detect(self.settings.bin_dir)
        return cached_scene_cuts(tools.ffmpeg.path, proxy, work_dir, duration, token, self._reporter(source_id, token, start, span))

    def _apply(self, source_id: int, settings: FindSettings, sig: Signals, duration: int, token: CancelToken) -> None:
        """Replace the source's suggested clips with the new picks. Clips the user kept or edited stay."""
        with self.db.connect() as conn:
            kept = conn.execute(
                "SELECT start_ms, end_ms FROM clips WHERE source_id = ? AND status != 'suggested'", (source_id,)
            ).fetchall()
            result = find_clips(settings, sig, duration, [(r["start_ms"], r["end_ms"]) for r in kept], token.raise_if_cancelled)
            token.raise_if_cancelled()
            removed = [r["id"] for r in conn.execute("SELECT id FROM clips WHERE source_id = ? AND status = 'suggested'", (source_id,))]
            exports.delete_clips(conn, self.export_manager, removed)
            base = conn.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 FROM clips WHERE source_id = ?", (source_id,)).fetchone()[0]
            created = []
            for i, cand in enumerate(result.chosen):
                cur = conn.execute(
                    """INSERT INTO clips (source_id, start_ms, end_ms, title, status, score, score_reasons_json,
                                          sort_order, created_at)
                       VALUES (?, ?, ?, ?, 'suggested', ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))""",
                    (source_id, cand.start, cand.end, cand.title, cand.score, json.dumps(cand.reasons), base + i),
                )
                created.append(clips.get(conn, cur.lastrowid))
            result_json = {
                "notes": result.notes,
                "mode_used": result.mode_used,
                "clip_count": len(result.chosen),
                "pool": [c.to_dict() for c in result.pool],
                "shown": [[c.start, c.end] for c in result.chosen],
            }
            conn.execute(
                """UPDATE analyses SET status = 'done', stage = NULL, progress = 1, error = NULL, result_json = ?,
                     updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE source_id = ?""",
                (json.dumps(result_json), source_id),
            )
            analysis = get(conn, source_id)
        for clip_id in removed:
            self.events.emit("clip_deleted", {"id": clip_id, "source_id": source_id})
        for clip in created:
            self.events.emit("clip", clip)
        self.events.emit("analysis", analysis)
