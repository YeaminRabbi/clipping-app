import json
import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .. import exports
from ..aspects import ASPECTS, default_crop

router = APIRouter(tags=["exports"])


class ExportPreset(BaseModel):
    codec: Literal["h264", "hevc"] = "h264"
    quality: Literal["high", "balanced", "small"] = "high"
    resolution: Literal[1080, 720] = 1080
    fps: Literal["source", "30", "60"] = "source"
    hardware: bool = True
    # How to frame sizes that weren't set up in the editor.
    default_framing: Literal["smart", "center", "fit"] = "smart"
    # Captions are optional: burn them into the video, write a .srt file next to it, or both.
    captions: Literal["off", "burn", "burn_srt", "srt"] = "off"
    # Also bundle the finished videos (and .srt files) into one ZIP.
    zip: bool = False
    output_dir: str
    name_template: str = Field(default="{project}_{index}_{title}_{ratio}", min_length=1, max_length=200)


class ExportCreate(BaseModel):
    clip_ids: list[int] = Field(min_length=1, max_length=500)
    aspects: list[str] = Field(min_length=1)
    preset: ExportPreset


@router.post("/exports", status_code=201)
def create_exports(body: ExportCreate, request: Request) -> list[dict[str, Any]]:
    unknown = [a for a in body.aspects if a not in ASPECTS]
    if unknown:
        raise HTTPException(422, f"Unknown aspect ratio: {', '.join(unknown)}")
    if not Path(body.preset.output_dir).is_absolute():
        raise HTTPException(422, "Choose a folder to save the videos in")
    aspects = list(dict.fromkeys(body.aspects))
    preset_json = json.dumps(body.preset.model_dump())
    burn = body.preset.captions in ("burn", "burn_srt")
    srt = body.preset.captions in ("srt", "burn_srt")
    batch_id = uuid.uuid4().hex

    created: list[dict[str, Any]] = []
    with request.app.state.db.connect() as conn:
        project_id = conn.execute(
            "SELECT s.project_id FROM clips c JOIN sources s ON s.id = c.source_id WHERE c.id = ?", (body.clip_ids[0],)
        ).fetchone()
        if project_id is None:
            raise HTTPException(404, f"Clip {body.clip_ids[0]} not found")
        conn.execute(
            "INSERT INTO export_batches (id, project_id, zip) VALUES (?, ?, ?)", (batch_id, project_id[0], int(body.preset.zip))
        )
        for index, clip_id in enumerate(body.clip_ids, start=1):
            clip = conn.execute(
                """SELECT c.id, c.title, s.title AS source_title, s.width, s.height, p.name AS project_name
                   FROM clips c JOIN sources s ON s.id = c.source_id JOIN projects p ON p.id = s.project_id
                   WHERE c.id = ?""",
                (clip_id,),
            ).fetchone()
            if clip is None:
                raise HTTPException(404, f"Clip {clip_id} not found")
            for aspect in aspects:
                # Use the framing chosen in the editor; sizes never set up get the preset's default.
                # Smart framing is tracked when the export runs.
                framing = body.preset.default_framing
                if framing == "center":
                    mode, keyframes = "manual", [{"t": 0, **default_crop(aspect, clip["width"], clip["height"])}]
                else:
                    mode, keyframes = framing, []
                conn.execute(
                    """INSERT INTO clip_formats (clip_id, aspect, mode, crop_keyframes_json)
                       VALUES (?, ?, ?, ?) ON CONFLICT (clip_id, aspect) DO NOTHING""",
                    (clip_id, aspect, mode, json.dumps(keyframes)),
                )
                format_id = conn.execute(
                    "SELECT id FROM clip_formats WHERE clip_id = ? AND aspect = ?", (clip_id, aspect)
                ).fetchone()["id"]
                name = exports.render_name(
                    body.preset.name_template,
                    project=clip["project_name"],
                    source=clip["source_title"] or "",
                    title=clip["title"] or f"Clip {index}",
                    index=f"{index:02d}",
                    ratio=aspect.replace(":", "x"),
                )
                cur = conn.execute(
                    """INSERT INTO export_jobs (clip_format_id, preset_json, output_name, batch_id, burn_captions, export_srt)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (format_id, preset_json, name, batch_id, int(burn), int(srt)),
                )
                created.append(exports.get_job(conn, cur.lastrowid))
    for job in created:
        request.app.state.exports.submit(job)
    return created


@router.get("/projects/{project_id}/exports")
def list_exports(project_id: int, request: Request) -> list[dict[str, Any]]:
    with request.app.state.db.connect() as conn:
        return exports.list_jobs(conn, project_id)


def _job_or_404(request: Request, job_id: int) -> dict[str, Any]:
    with request.app.state.db.connect() as conn:
        job = exports.get_job(conn, job_id)
    if job is None:
        raise HTTPException(404, "Export not found")
    return job


@router.post("/exports/{job_id}/cancel")
def cancel_export(job_id: int, request: Request) -> dict[str, Any]:
    job = _job_or_404(request, job_id)
    if job["status"] not in exports.ACTIVE_STATUSES or not request.app.state.exports.cancel(job_id):
        raise HTTPException(409, "This export is not running")
    return job


@router.post("/exports/{job_id}/retry")
def retry_export(job_id: int, request: Request) -> dict[str, Any]:
    job = _job_or_404(request, job_id)
    if job["status"] not in ("failed", "cancelled"):
        raise HTTPException(409, "Only failed or cancelled exports can be retried")
    with request.app.state.db.connect() as conn:
        conn.execute(
            "UPDATE export_jobs SET status = 'queued', progress = 0, error = NULL, output_path = NULL WHERE id = ?",
            (job_id,),
        )
        job = exports.get_job(conn, job_id)
    request.app.state.exports.submit(job)
    return job


@router.delete("/projects/{project_id}/exports", status_code=204)
def clear_finished_exports(project_id: int, request: Request) -> None:
    """Remove finished jobs from the list. Exported files are left where they are."""
    placeholders = ",".join("?" * len(exports.FINISHED_STATUSES))
    with request.app.state.db.connect() as conn:
        conn.execute(
            f"""DELETE FROM export_jobs WHERE status IN ({placeholders}) AND clip_format_id IN (
                  SELECT f.id FROM clip_formats f JOIN clips c ON c.id = f.clip_id
                  JOIN sources s ON s.id = c.source_id WHERE s.project_id = ?)""",
            (*exports.FINISHED_STATUSES, project_id),
        )


@router.get("/projects/{project_id}/export-batches")
def list_batches(project_id: int, request: Request) -> list[dict[str, Any]]:
    """Export batches that asked for a ZIP, newest first."""
    with request.app.state.db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM export_batches WHERE project_id = ? AND zip = 1 ORDER BY created_at DESC", (project_id,)
        ).fetchall()
    return [exports.batch_to_dict(r) for r in rows]
