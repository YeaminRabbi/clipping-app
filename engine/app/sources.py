"""Reading source rows into the shape the API returns."""

import sqlite3
from pathlib import Path
from typing import Any

from .media.timeline import PEAKS_PER_SECOND, thumb_layout

def source_dir(settings, project_id: int, source_id: int) -> Path:
    """Where the app keeps a source's generated files (download, proxy, thumbnails, transcript)."""
    return settings.projects_dir / str(project_id) / "sources" / str(source_id)


ACTIVE_STATUSES = ("queued", "downloading", "probing", "processing")
RETRYABLE_STATUSES = ("failed", "cancelled")


def to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "origin": row["origin"],
        "url": row["url"],
        "path": row["path"],
        "title": row["title"],
        "status": row["status"],
        "progress": row["progress"],
        "error": row["error"],
        "duration_ms": row["duration_ms"],
        "fps": row["fps"],
        "width": row["width"],
        "height": row["height"],
        "size_bytes": row["size_bytes"],
        "video_codec": row["video_codec"],
        "audio_codec": row["audio_codec"],
        "has_audio": bool(row["has_audio"]),
        "is_vfr": bool(row["is_vfr"]),
        # Media is served by the engine; the client appends its token as a query parameter.
        "proxy_url": f"/media/sources/{row['id']}/proxy" if row["proxy_path"] else None,
        "poster_url": f"/media/sources/{row['id']}/poster" if row["poster_path"] else None,
        "timeline": _timeline(row),
        "created_at": row["created_at"],
    }


TIMELINE_ASSETS = ("thumbs.jpg", "waveform.bin")


def timeline_assets_ready(work_dir: Path) -> bool:
    return all((work_dir / name).is_file() for name in TIMELINE_ASSETS)


def _timeline(row: sqlite3.Row) -> dict[str, Any] | None:
    """Timeline assets that exist (each URL is null until its file does). They sit next to the proxy
    and are made by the import job, or in the background at startup for videos imported before
    they existed."""
    if row["status"] != "ready" or not (row["duration_ms"] and row["width"] and row["height"]) or not row["proxy_path"]:
        return None
    work_dir = Path(row["proxy_path"]).parent
    thumbs = (work_dir / "thumbs.jpg").is_file()
    waveform = (work_dir / "waveform.bin").is_file()
    if not (thumbs or waveform):
        return None
    return {
        "thumbs_url": f"/media/sources/{row['id']}/thumbs" if thumbs else None,
        "thumbs": thumb_layout(row["duration_ms"], row["width"], row["height"]).as_dict(),
        "waveform_url": f"/media/sources/{row['id']}/waveform" if waveform else None,
        "peaks_per_second": PEAKS_PER_SECOND,
    }


def get(conn: sqlite3.Connection, source_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
    return to_dict(row) if row else None


def list_for_project(conn: sqlite3.Connection, project_id: int) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM sources WHERE project_id = ? ORDER BY id DESC", (project_id,)).fetchall()
    return [to_dict(r) for r in rows]
