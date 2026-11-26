from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ..live import LiveManager
from ..media import MediaError

router = APIRouter(tags=["live"])


class RecordingCreate(BaseModel):
    url: str
    project_id: int
    quality: Literal["source", "1080", "720"] = "source"
    # Where the finished recording is saved. Each recording becomes one MP4 file there.
    output_dir: str


def _manager(request: Request) -> LiveManager:
    return request.app.state.live


@router.get("/live/recordings")
def list_recordings(request: Request) -> list[dict[str, Any]]:
    return _manager(request).all()


@router.post("/live/recordings", status_code=201)
def start_recording(body: RecordingCreate, request: Request) -> dict[str, Any]:
    url = body.url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(422, "Enter the full link of the live stream, starting with https://")
    output_dir = Path(body.output_dir.strip())
    if not output_dir.is_absolute():
        raise HTTPException(422, "The recordings folder must be a full path")
    with request.app.state.db.connect() as conn:
        if not conn.execute("SELECT 1 FROM projects WHERE id = ?", (body.project_id,)).fetchone():
            raise HTTPException(404, "Project not found")
    try:
        return _manager(request).begin(url, body.project_id, body.quality, output_dir.resolve())
    except MediaError as err:
        raise HTTPException(422, str(err)) from err


def _or_404(value: dict[str, Any] | None) -> dict[str, Any]:
    if value is None:
        raise HTTPException(404, "Recording not found")
    return value


@router.post("/live/recordings/{rec_id}/stop")
def stop_recording(rec_id: int, request: Request) -> dict[str, Any]:
    """Stop and save: the recording is joined into one file and imported into its project."""
    return _or_404(_manager(request).stop(rec_id))


@router.post("/live/recordings/{rec_id}/save")
def save_interrupted(rec_id: int, request: Request) -> dict[str, Any]:
    """Save a recording that was cut off when the app closed."""
    result = _manager(request).save_interrupted(rec_id)
    if result is None:
        raise HTTPException(409, "Only an interrupted recording can be saved this way")
    return result


@router.post("/live/recordings/{rec_id}/marks")
def mark_moment(rec_id: int, request: Request) -> dict[str, Any]:
    """Mark what's happening now. Each mark becomes a clip once the recording is imported."""
    result = _manager(request).mark(rec_id)
    if result is None:
        raise HTTPException(409, "Moments can only be marked while recording")
    return result


@router.delete("/live/recordings/{rec_id}", status_code=204)
def discard_recording(rec_id: int, request: Request) -> None:
    """Stop without saving, or remove a finished entry from the list (its saved file is kept)."""
    try:
        found = _manager(request).discard(rec_id)
    except MediaError as err:
        raise HTTPException(409, str(err)) from err
    if not found:
        raise HTTPException(404, "Recording not found")


@router.get("/media/live/{rec_id}/{part}/{name}")
def preview_file(rec_id: int, part: int, name: str, request: Request) -> FileResponse:
    path = _manager(request).preview_file(rec_id, part, name)
    if path is None:
        raise HTTPException(404, "Not available")
    media_type = "application/vnd.apple.mpegurl" if name.endswith(".m3u8") else "video/mp4"
    # The playlist changes every couple of seconds; never serve a cached copy.
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "no-store"})
