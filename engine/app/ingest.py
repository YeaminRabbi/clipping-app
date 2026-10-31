"""Background import of sources: download (for links), probe, poster and proxy generation."""

import logging
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from . import ffmpeg, sources
from .config import Settings
from .db import Database
from .events import EventHub
from .media import CancelToken, Cancelled, MediaError
from .media.download import download
from .media.probe import probe
from .media.timeline import make_thumbs, make_waveform, thumb_layout
from .media.transcode import make_poster, make_proxy

log = logging.getLogger("engine.ingest")

# Share of the progress bar given to downloading, for link imports.
DOWNLOAD_WEIGHT = 0.7
# Write progress to the DB / UI at most this often.
PROGRESS_INTERVAL_S = 0.4


class IngestManager:
    def __init__(self, settings: Settings, db: Database, events: EventHub, max_workers: int = 2):
        self.settings = settings
        self.db = db
        self.events = events
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ingest")
        self.tokens: dict[int, CancelToken] = {}
        self._asset_locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def start(self) -> None:
        # Anything still marked active was cut off by the engine stopping; let the user retry it.
        placeholders = ",".join("?" * len(sources.ACTIVE_STATUSES))
        with self.db.connect() as conn:
            conn.execute(
                f"UPDATE sources SET status = 'failed', error = ? WHERE status IN ({placeholders})",
                ("Import was interrupted because the app closed", *sources.ACTIVE_STATUSES),
            )

    def shutdown(self) -> None:
        for token in self.tokens.values():
            token.cancel()
        self.executor.shutdown(wait=False, cancel_futures=True)

    def source_dir(self, project_id: int, source_id: int) -> Path:
        return sources.source_dir(self.settings, project_id, source_id)

    def project_dir(self, project_id: int) -> Path:
        return self.settings.projects_dir / str(project_id)

    def submit(self, source: dict[str, Any]) -> None:
        """Queue an import. Announces the queued source right away, since workers may all be busy."""
        token = CancelToken()
        self.tokens[source["id"]] = token
        self.events.emit("source", source)
        self.executor.submit(self._run, source["id"], token)

    def cancel(self, source_id: int) -> bool:
        token = self.tokens.get(source_id)
        if token is None:
            return False
        token.cancel()
        return True

    def remove_files(self, path: Path) -> None:
        # Files may still be open by a job that is shutting down; the job retries when it exits.
        shutil.rmtree(path, ignore_errors=True)

    # --- worker side -------------------------------------------------------------------------

    def _update(self, source_id: int, **fields: Any) -> dict[str, Any] | None:
        assignments = ", ".join(f"{k} = ?" for k in fields)
        with self.db.connect() as conn:
            conn.execute(f"UPDATE sources SET {assignments} WHERE id = ?", (*fields.values(), source_id))
            source = sources.get(conn, source_id)
        if source:
            self.events.emit("source", source)
        return source

    def _make_timeline_assets(
        self, work_dir: Path, duration_ms: int, width: int, height: int, has_audio: bool, token: CancelToken
    ) -> None:
        """Thumbnail sprite and waveform for the editor. Failures only degrade the timeline, so they're logged."""
        tools = ffmpeg.detect(self.settings.bin_dir)
        proxy = work_dir / "proxy.mp4"
        with self._asset_lock(work_dir):
            thumbs = work_dir / "thumbs.jpg"
            if not thumbs.is_file():
                try:
                    make_thumbs(tools.ffmpeg.path, proxy, thumbs, thumb_layout(duration_ms, width, height), duration_ms, token)
                except MediaError as err:
                    log.warning("Thumbnails failed for %s: %s", work_dir, err)
            waveform = work_dir / "waveform.bin"
            if not waveform.is_file() and not has_audio:
                waveform.write_bytes(b"")
            elif not waveform.is_file():
                try:
                    make_waveform(tools.ffmpeg.path, proxy, waveform, token)
                except MediaError as err:
                    log.warning("Waveform failed for %s: %s", work_dir, err)

    def _asset_lock(self, work_dir: Path) -> threading.Lock:
        with self._locks_guard:
            return self._asset_locks.setdefault(str(work_dir), threading.Lock())

    def ensure_timeline_assets(self, source: dict[str, Any]) -> Path:
        """Generate missing timeline assets on demand (for sources imported before they existed)."""
        work_dir = self.source_dir(source["project_id"], source["id"])
        if not ((work_dir / "thumbs.jpg").is_file() and (work_dir / "waveform.bin").is_file()):
            self._make_timeline_assets(
                work_dir, source["duration_ms"], source["width"], source["height"], source["has_audio"], CancelToken()
            )
        return work_dir

    def _release(self, source_id: int, token: CancelToken) -> None:
        # A retry may already have registered a new token for this source; leave that one alone.
        if self.tokens.get(source_id) is token:
            del self.tokens[source_id]

    def _progress_reporter(self, source_id: int, start: float, span: float):
        last = {"t": 0.0}

        def report(fraction: float) -> None:
            now = time.monotonic()
            if now - last["t"] >= PROGRESS_INTERVAL_S:
                last["t"] = now
                self._update(source_id, progress=round(start + span * fraction, 4))

        return report

    def _run(self, source_id: int, token: CancelToken) -> None:
        with self.db.connect() as conn:
            row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
        if row is None or token.cancelled:
            # Cancelled while still waiting in the queue.
            if row is not None:
                self._update(source_id, status="cancelled", error=None)
            self._release(source_id, token)
            return

        work_dir = self.source_dir(row["project_id"], source_id)
        work_dir.mkdir(parents=True, exist_ok=True)
        tools = ffmpeg.detect(self.settings.bin_dir)

        try:
            if not tools.ok:
                raise MediaError("FFmpeg was not found. Run \"npm run bundle:ffmpeg\" and restart the engine.")

            process_start = 0.0
            if row["origin"] == "url":
                self._update(source_id, status="downloading", progress=0, error=None)
                result = download(
                    row["url"],
                    work_dir,
                    tools.ffmpeg.path,
                    token,
                    on_progress=self._progress_reporter(source_id, 0, DOWNLOAD_WEIGHT),
                    on_title=lambda title: self._update(source_id, title=title),
                )
                src = result.path
                self._update(source_id, path=str(src), **({"title": result.title} if result.title else {}))
                process_start = DOWNLOAD_WEIGHT
            else:
                src = Path(row["path"])
                if not src.is_file():
                    raise MediaError(f"File not found: {src}")

            token.raise_if_cancelled()
            self._update(source_id, status="probing", progress=process_start, error=None)
            info = probe(tools.ffprobe.path, src)
            self._update(
                source_id,
                duration_ms=info.duration_ms,
                fps=info.fps,
                width=info.width,
                height=info.height,
                size_bytes=info.size_bytes or src.stat().st_size,
                video_codec=info.video_codec,
                audio_codec=info.audio_codec,
                has_audio=int(info.has_audio),
                is_vfr=int(info.is_vfr),
            )

            token.raise_if_cancelled()
            self._update(source_id, status="processing")
            poster = work_dir / "poster.jpg"
            try:
                make_poster(tools.ffmpeg.path, src, poster, info, token)
                self._update(source_id, poster_path=str(poster))
            except MediaError as err:
                log.warning("Poster failed for source %s: %s", source_id, err)

            proxy = work_dir / "proxy.mp4"
            make_proxy(
                tools.ffmpeg.path,
                src,
                proxy,
                info,
                token,
                on_progress=self._progress_reporter(source_id, process_start, 1 - process_start),
            )
            self._update(source_id, proxy_path=str(proxy))
            self._make_timeline_assets(work_dir, info.duration_ms, info.width, info.height, info.has_audio, token)
            self._update(source_id, status="ready", progress=1, error=None)
        except Cancelled:
            self._update(source_id, status="cancelled", error=None)
        except MediaError as err:
            self._update(source_id, status="failed", error=str(err))
        except Exception as err:
            log.exception("Import failed for source %s", source_id)
            self._update(source_id, status="failed", error=f"Unexpected error: {err}")
        finally:
            self._release(source_id, token)
            # If the source was deleted while running, its files couldn't be removed then; do it now.
            with self.db.connect() as conn:
                still_exists = conn.execute("SELECT 1 FROM sources WHERE id = ?", (source_id,)).fetchone()
            if not still_exists:
                self.remove_files(work_dir)
