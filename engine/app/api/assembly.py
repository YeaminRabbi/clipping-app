"""Audio assets and ordered collages, available in the editor and through the clip API command."""

import json
import shutil
import subprocess
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .. import ffmpeg, sources
from .exports import ExportCreate, ExportPreset, enqueue_exports

router = APIRouter(tags=["assembly"])


class AudioImport(BaseModel):
    path: str


@router.post("/projects/{project_id}/audio", status_code=201)
def import_audio(project_id: int, body: AudioImport, request: Request):
    path = Path(body.path)
    if not path.is_absolute() or not path.is_file():
        raise HTTPException(422, "Choose an existing audio file")
    tools = ffmpeg.detect(request.app.state.settings.bin_dir)
    if not tools.ok:
        raise HTTPException(422, "FFmpeg and ffprobe are required")
    try:
        result = subprocess.run([tools.ffprobe.path, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                                capture_output=True, text=True, timeout=30, creationflags=ffmpeg.NO_WINDOW, check=True)
        data = json.loads(result.stdout)
        if not any(s.get("codec_type") == "audio" for s in data.get("streams", [])):
            raise ValueError("No audio stream")
        duration = round(float(data["format"]["duration"]) * 1000)
        if duration <= 0:
            raise ValueError("Empty audio")
    except (ValueError, KeyError, OSError, subprocess.SubprocessError):
        raise HTTPException(422, "Could not read the audio file or its duration")
    with request.app.state.db.connect() as conn:
        if not conn.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone():
            raise HTTPException(404, "Project not found")
        folder = request.app.state.settings.projects_dir / str(project_id) / "audio"
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / (uuid.uuid4().hex + path.suffix)
        shutil.copyfile(path, dest)
        try:
            asset_id = conn.execute("INSERT INTO audio_assets (project_id, path, name, duration_ms) VALUES (?, ?, ?, ?)",
                                    (project_id, str(dest), path.name, duration)).lastrowid
        except Exception:
            dest.unlink(missing_ok=True)
            raise
    return {"id": asset_id, "name": path.name, "duration_ms": duration, "url": f"/media/audio/{asset_id}"}


@router.get("/projects/{project_id}/audio")
def list_audio(project_id: int, request: Request):
    with request.app.state.db.connect() as conn:
        rows = conn.execute("SELECT * FROM audio_assets WHERE project_id = ? ORDER BY id", (project_id,)).fetchall()
    return [{"id": r["id"], "name": r["name"], "duration_ms": r["duration_ms"], "url": f"/media/audio/{r['id']}"} for r in rows]


@router.get("/media/audio/{asset_id}")
def audio_media(asset_id: int, request: Request):
    with request.app.state.db.connect() as conn:
        row = conn.execute("SELECT path FROM audio_assets WHERE id = ?", (asset_id,)).fetchone()
    if row is None or not Path(row["path"]).is_file():
        raise HTTPException(404, "Audio file not found")
    return FileResponse(row["path"])


class CollageCreate(BaseModel):
    clip_ids: list[int] = Field(min_length=2, max_length=100)
    title: str = Field(default="Collage", min_length=1, max_length=200)
    aspect: str = "9:16"
    resolution: int = 720


@router.post("/projects/{project_id}/collages", status_code=202)
def create_collage(project_id: int, body: CollageCreate, request: Request):
    from ..aspects import ASPECTS
    if body.aspect not in ASPECTS or body.resolution not in (720, 1080):
        raise HTTPException(422, "Choose a supported aspect ratio and resolution")
    with request.app.state.db.connect() as conn:
        for clip_id in body.clip_ids:
            row = conn.execute("SELECT s.project_id, s.status FROM clips c JOIN sources s ON s.id = c.source_id WHERE c.id = ?", (clip_id,)).fetchone()
            if row is None or row["project_id"] != project_id:
                raise HTTPException(422, "All clips must belong to this project")
            if row["status"] != "ready":
                raise HTTPException(409, "Wait until all videos finish importing")
        source_id = conn.execute("INSERT INTO sources (project_id, origin, title, status) VALUES (?, 'file', ?, 'queued')",
                                 (project_id, body.title.strip() or "Collage")).lastrowid
    work = request.app.state.ingest.source_dir(project_id, source_id)
    work.mkdir(parents=True, exist_ok=True)
    try:
        jobs = enqueue_exports(ExportCreate(clip_ids=body.clip_ids, aspects=[body.aspect], preset=ExportPreset(
            output_dir=str(work / "parts"), fps="30", default_framing="fit", resolution=body.resolution,
            name_template="{index}_{title}", hardware=False,
        )), request, collage_source_id=source_id)
        with request.app.state.db.connect() as conn:
            conn.execute("UPDATE sources SET path = ?, composition_json = ? WHERE id = ?",
                         (str(work / "collage.mp4"), json.dumps({"jobs": [j["id"] for j in jobs]}), source_id))
            source = sources.get(conn, source_id)
    except Exception:
        with request.app.state.db.connect() as conn:
            conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
        raise
    request.app.state.ingest.submit(source)
    return source
