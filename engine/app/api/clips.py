import json
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .. import clips, exports, sources
from ..aspects import ASPECTS
from ..media import CancelToken
from ..reframe.service import track_clip

router = APIRouter(tags=["clips"])

MIN_CLIP_MS = 100


class ClipCreate(BaseModel):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    title: str | None = Field(default=None, max_length=200)


class ClipUpdate(BaseModel):
    start_ms: int | None = Field(default=None, ge=0)
    end_ms: int | None = Field(default=None, gt=0)
    title: str | None = Field(default=None, max_length=200)
    status: Literal["suggested", "kept", "rejected"] | None = None


class Crop(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    w: float = Field(gt=0, le=1)
    h: float = Field(gt=0, le=1)


class FitStyle(BaseModel):
    background: Literal["blur", "black", "white"] = "blur"
    dim: float = Field(default=0.25, ge=0, le=0.6)
    zoom: float = Field(default=1.0, ge=1.0, le=1.5)
    position: Literal["center", "top"] = "center"


class FormatUpdate(BaseModel):
    """manual: a fixed crop. smart: follow faces (tracking runs now). fit: whole frame, styled by `fit`."""

    mode: Literal["manual", "fit", "smart"]
    crop: Crop | None = None
    fit: FitStyle | None = None


def _ready_source(conn, source_id: int):
    source = conn.execute("SELECT id, status, duration_ms FROM sources WHERE id = ?", (source_id,)).fetchone()
    if source is None:
        raise HTTPException(404, "Source not found")
    if source["status"] != "ready":
        raise HTTPException(409, "This video is still importing")
    return source


def _check_range(start_ms: int, end_ms: int, duration_ms: int) -> None:
    if end_ms - start_ms < MIN_CLIP_MS:
        raise HTTPException(422, "A clip must be at least 0.1 seconds long")
    if end_ms > duration_ms:
        raise HTTPException(422, "The clip ends after the video does")


def _clip_or_404(conn, clip_id: int) -> dict[str, Any]:
    clip = clips.get(conn, clip_id)
    if clip is None:
        raise HTTPException(404, "Clip not found")
    return clip


def _publish(request: Request, event: str, data: Any) -> None:
    request.app.state.events.emit(event, data)


@router.get("/sources/{source_id}/clips")
def list_source_clips(source_id: int, request: Request) -> list[dict[str, Any]]:
    with request.app.state.db.connect() as conn:
        if not conn.execute("SELECT 1 FROM sources WHERE id = ?", (source_id,)).fetchone():
            raise HTTPException(404, "Source not found")
        return clips.list_for_source(conn, source_id)


@router.get("/projects/{project_id}/clips")
def list_project_clips(project_id: int, request: Request) -> list[dict[str, Any]]:
    with request.app.state.db.connect() as conn:
        if not conn.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone():
            raise HTTPException(404, "Project not found")
        return clips.list_for_project(conn, project_id)


@router.post("/sources/{source_id}/clips", status_code=201)
def create_clip(source_id: int, body: ClipCreate, request: Request) -> dict[str, Any]:
    with request.app.state.db.connect() as conn:
        source = _ready_source(conn, source_id)
        _check_range(body.start_ms, body.end_ms, source["duration_ms"])
        count = conn.execute("SELECT COUNT(*) FROM clips WHERE source_id = ?", (source_id,)).fetchone()[0]
        title = (body.title or "").strip() or f"Clip {count + 1}"
        cur = conn.execute(
            """INSERT INTO clips (source_id, start_ms, end_ms, title, status, sort_order, created_at)
               VALUES (?, ?, ?, ?, 'kept', ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))""",
            (source_id, body.start_ms, body.end_ms, title, count),
        )
        clip = clips.get(conn, cur.lastrowid)
    _publish(request, "clip", clip)
    return clip


@router.patch("/clips/{clip_id}")
def update_clip(clip_id: int, body: ClipUpdate, request: Request) -> dict[str, Any]:
    with request.app.state.db.connect() as conn:
        clip = _clip_or_404(conn, clip_id)
        source = _ready_source(conn, clip["source_id"])
        start = body.start_ms if body.start_ms is not None else clip["start_ms"]
        end = body.end_ms if body.end_ms is not None else clip["end_ms"]
        _check_range(start, end, source["duration_ms"])
        title = clip["title"] if body.title is None else (body.title.strip() or clip["title"])
        # Editing a suggested clip means the user wants it: re-running auto clipping won't remove it.
        status = body.status or ("kept" if clip["status"] == "suggested" else clip["status"])
        conn.execute(
            "UPDATE clips SET start_ms = ?, end_ms = ?, title = ?, status = ? WHERE id = ?",
            (start, end, title, status, clip_id),
        )
        clip = clips.get(conn, clip_id)
    _publish(request, "clip", clip)
    return clip


@router.put("/clips/{clip_id}/formats/{aspect_key}")
def set_format(clip_id: int, aspect_key: str, body: FormatUpdate, request: Request) -> dict[str, Any]:
    aspect = aspect_key.replace("x", ":")  # allow "9x16" in URLs
    if aspect not in ASPECTS:
        raise HTTPException(404, "Unknown aspect ratio")
    if body.mode == "manual" and body.crop is None:
        raise HTTPException(422, "Manual framing needs a crop")
    if body.crop and (body.crop.x + body.crop.w > 1.0001 or body.crop.y + body.crop.h > 1.0001):
        raise HTTPException(422, "Crop must stay inside the frame")
    keyframes = [{"t": 0, **body.crop.model_dump()}] if body.crop else []
    options: dict[str, Any] = (body.fit or FitStyle()).model_dump() if body.mode == "fit" else {}

    with request.app.state.db.connect() as conn:
        clip = _clip_or_404(conn, clip_id)
        source = conn.execute("SELECT * FROM sources WHERE id = ?", (clip["source_id"],)).fetchone()
    if body.mode == "smart":
        # Tracking takes a few seconds; FastAPI runs this sync route in a worker thread.
        work_dir = sources.source_dir(request.app.state.settings, source["project_id"], source["id"])
        result = track_clip(
            request.app.state.settings, source, work_dir, clip["start_ms"], clip["end_ms"], aspect, CancelToken()
        )
        keyframes, options = result.keyframes, {"face_ratio": result.face_ratio}

    with request.app.state.db.connect() as conn:
        conn.execute(
            """INSERT INTO clip_formats (clip_id, aspect, mode, crop_keyframes_json, options_json) VALUES (?, ?, ?, ?, ?)
               ON CONFLICT (clip_id, aspect) DO UPDATE SET mode = excluded.mode,
                 crop_keyframes_json = excluded.crop_keyframes_json, options_json = excluded.options_json""",
            (clip_id, aspect, body.mode, json.dumps(keyframes), json.dumps(options)),
        )
        conn.execute("UPDATE clips SET status = 'kept' WHERE id = ? AND status = 'suggested'", (clip_id,))
        clip = clips.get(conn, clip_id)
    _publish(request, "clip", clip)
    return clip


@router.delete("/clips/{clip_id}", status_code=204)
def delete_clip(clip_id: int, request: Request) -> None:
    with request.app.state.db.connect() as conn:
        clip = _clip_or_404(conn, clip_id)
        for job_id in exports.active_job_ids(conn, clip_id=clip_id):
            request.app.state.exports.cancel(job_id)
        conn.execute("DELETE FROM clips WHERE id = ?", (clip_id,))
    _publish(request, "clip_deleted", {"id": clip_id, "source_id": clip["source_id"]})
