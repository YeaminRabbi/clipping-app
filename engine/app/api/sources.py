from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, model_validator

from .. import exports, sources

router = APIRouter(tags=["sources"])


class SourceCreate(BaseModel):
    url: str | None = None
    path: str | None = None

    @model_validator(mode="after")
    def exactly_one(self):
        if bool(self.url) == bool(self.path):
            raise ValueError("Provide either a url or a file path")
        return self


def _validate_url(url: str) -> str:
    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(422, "Enter a full link starting with http:// or https://")
    return url


def _validate_path(raw: str) -> Path:
    path = Path(raw.strip())
    if not path.is_absolute():
        raise HTTPException(422, "File path must be absolute")
    if not path.is_file():
        raise HTTPException(422, f"File not found: {path}")
    # Resolving makes the path absolute, so it can never be mistaken for an FFmpeg option.
    return path.resolve()


def _get_or_404(request: Request, source_id: int) -> dict[str, Any]:
    with request.app.state.db.connect() as conn:
        source = sources.get(conn, source_id)
    if source is None:
        raise HTTPException(404, "Source not found")
    return source


@router.get("/projects/{project_id}/sources")
def list_sources(project_id: int, request: Request) -> list[dict[str, Any]]:
    with request.app.state.db.connect() as conn:
        if not conn.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone():
            raise HTTPException(404, "Project not found")
        return sources.list_for_project(conn, project_id)


@router.post("/projects/{project_id}/sources", status_code=201)
def add_source(project_id: int, body: SourceCreate, request: Request) -> dict[str, Any]:
    if body.url:
        values = ("url", _validate_url(body.url), None, None)
    else:
        path = _validate_path(body.path or "")
        values = ("file", None, str(path), path.name)

    with request.app.state.db.connect() as conn:
        if not conn.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone():
            raise HTTPException(404, "Project not found")
        cur = conn.execute(
            "INSERT INTO sources (project_id, origin, url, path, title, status) VALUES (?, ?, ?, ?, ?, 'queued')",
            (project_id, *values),
        )
        conn.execute(
            "UPDATE projects SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?", (project_id,)
        )
        source = sources.get(conn, cur.lastrowid)
    request.app.state.ingest.submit(source)
    return source


@router.get("/sources/{source_id}")
def get_source(source_id: int, request: Request) -> dict[str, Any]:
    return _get_or_404(request, source_id)


@router.post("/sources/{source_id}/cancel")
def cancel_source(source_id: int, request: Request) -> dict[str, Any]:
    source = _get_or_404(request, source_id)
    if source["status"] not in sources.ACTIVE_STATUSES or not request.app.state.ingest.cancel(source_id):
        raise HTTPException(409, "This import is not running")
    return source


@router.post("/sources/{source_id}/retry")
def retry_source(source_id: int, request: Request) -> dict[str, Any]:
    source = _get_or_404(request, source_id)
    if source["status"] not in sources.RETRYABLE_STATUSES:
        raise HTTPException(409, "Only failed or cancelled imports can be retried")
    with request.app.state.db.connect() as conn:
        conn.execute("UPDATE sources SET status = 'queued', progress = 0, error = NULL WHERE id = ?", (source_id,))
        source = sources.get(conn, source_id)
    request.app.state.ingest.submit(source)
    return source


@router.delete("/sources/{source_id}", status_code=204)
def delete_source(source_id: int, request: Request) -> None:
    source = _get_or_404(request, source_id)
    ingest = request.app.state.ingest
    ingest.cancel(source_id)
    request.app.state.analysis.cancel(source_id)
    with request.app.state.db.connect() as conn:
        for job_id in exports.active_job_ids(conn, source_id=source_id):
            request.app.state.exports.cancel(job_id)
        conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
    # Only the app's own folder is removed; a user's local file imported in place is never touched.
    ingest.remove_files(ingest.source_dir(source["project_id"], source_id))


@router.get("/media/sources/{source_id}/thumbs")
def source_thumbs(source_id: int, request: Request) -> FileResponse:
    return FileResponse(_timeline_asset(request, source_id, "thumbs.jpg"), media_type="image/jpeg")


@router.get("/media/sources/{source_id}/waveform")
def source_waveform(source_id: int, request: Request) -> FileResponse:
    return FileResponse(_timeline_asset(request, source_id, "waveform.bin"), media_type="application/octet-stream")


def _timeline_asset(request: Request, source_id: int, name: str) -> Path:
    source = _get_or_404(request, source_id)
    if source["status"] != "ready":
        raise HTTPException(404, "Media not available")
    path = request.app.state.ingest.ensure_timeline_assets(source) / name
    if not path.is_file():
        raise HTTPException(404, "Media not available")
    return path


@router.get("/media/sources/{source_id}/{kind}")
def source_media(source_id: int, kind: str, request: Request) -> FileResponse:
    if kind not in ("proxy", "poster"):
        raise HTTPException(404, "Unknown media")
    with request.app.state.db.connect() as conn:
        row = conn.execute(f"SELECT {kind}_path AS p FROM sources WHERE id = ?", (source_id,)).fetchone()
    if row is None or not row["p"] or not Path(row["p"]).is_file():
        raise HTTPException(404, "Media not available")
    return FileResponse(row["p"], media_type="video/mp4" if kind == "proxy" else "image/jpeg")
