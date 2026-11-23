import json
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .. import clips
from ..analysis.manager import AlreadyRunning
from ..analysis.transcribe import MODELS
from ..captions.cues import apply_text_edit, in_clip
from ..captions.service import CaptionEdits, clip_cues, clip_words, project_style, resolved_style
from ..captions.styles import DEFAULT_TEMPLATE, FONTS, MAX_SIZE, MIN_SIZE, OVERRIDABLE, TEMPLATES, font_file

router = APIRouter(tags=["captions"])


COLOR = r"^#[0-9A-Fa-f]{6}$"


class StyleOverrides(BaseModel):
    """What may be changed on top of a template. Left out or null = the template's own value."""

    font: Literal[tuple(FONTS)] | None = None  # type: ignore[valid-type]
    size: int | None = Field(default=None, ge=MIN_SIZE, le=MAX_SIZE)
    uppercase: bool | None = None
    color: str | None = Field(default=None, pattern=COLOR)
    highlight: str | None = Field(default=None, pattern=rf"{COLOR}|^$")  # "" = no highlight
    position: Literal["top", "middle", "bottom"] | None = None


class StyleUpdate(BaseModel):
    template: Literal["bold_pop", "karaoke", "classic", "minimal"] = DEFAULT_TEMPLATE  # type: ignore[valid-type]
    overrides: StyleOverrides = Field(default_factory=StyleOverrides)


class CaptionEdit(BaseModel):
    """Replace the words at `indices` (one cue, as returned by GET) with `text`. Empty text deletes them."""

    indices: list[int] = Field(min_length=1)
    text: str = Field(max_length=500)


class TranscribeRequest(BaseModel):
    model: Literal[MODELS] = "base"  # type: ignore[valid-type]
    language: str | None = Field(default=None, max_length=8)


def _clip_or_404(conn, clip_id: int):
    row = conn.execute("SELECT * FROM clips WHERE id = ?", (clip_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Clip not found")
    return row


def _captions_payload(request: Request, clip_id: int) -> dict[str, Any]:
    with request.app.state.db.connect() as conn:
        clip = _clip_or_404(conn, clip_id)
        cues, edited, style = clip_cues(conn, request.app.state.settings, clip)
    return {
        "clip_id": clip_id,
        "status": "needs_transcript" if cues is None else "ready",
        "edited": edited,
        "cues": [c.to_dict() for c in cues or []],
        "style": style.to_dict(),
    }


@router.get("/caption-templates")
def caption_templates() -> dict[str, Any]:
    return {
        "default": DEFAULT_TEMPLATE,
        "templates": {k: v.to_dict() for k, v in TEMPLATES.items()},
        "fonts": [name for name in FONTS if font_file(name) is not None],
        "overridable": list(OVERRIDABLE),
    }


@router.get("/projects/{project_id}/caption-style")
def get_caption_style(project_id: int, request: Request) -> dict[str, Any]:
    with request.app.state.db.connect() as conn:
        template, overrides = project_style(conn, project_id)
        style = resolved_style(conn, project_id)
    return {"template": template, "overrides": overrides, "style": style.to_dict()}


@router.put("/projects/{project_id}/caption-style")
def set_caption_style(project_id: int, body: StyleUpdate, request: Request) -> dict[str, Any]:
    overrides = body.overrides.model_dump(exclude_none=True)
    with request.app.state.db.connect() as conn:
        if not conn.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone():
            raise HTTPException(404, "Project not found")
        conn.execute(
            """INSERT INTO caption_styles (project_id, template, options_json) VALUES (?, ?, ?)
               ON CONFLICT (project_id) DO UPDATE SET template = excluded.template, options_json = excluded.options_json""",
            (project_id, body.template, json.dumps(overrides)),
        )
    request.app.state.events.emit("caption_style", {"project_id": project_id})
    return get_caption_style(project_id, request)


@router.get("/clips/{clip_id}/captions")
def get_captions(clip_id: int, request: Request) -> dict[str, Any]:
    return _captions_payload(request, clip_id)


@router.post("/clips/{clip_id}/captions/edit")
def edit_captions(clip_id: int, body: CaptionEdit, request: Request) -> dict[str, Any]:
    with request.app.state.db.connect() as conn:
        clip = _clip_or_404(conn, clip_id)
        words, _ = clip_words(conn, request.app.state.settings, clip, clamp=False)
        if words is None:
            raise HTTPException(409, "Transcribe the video first")
        # Increasing, but not necessarily consecutive: a cue skips the words Tighten cuts.
        in_order = all(a < b for a, b in zip(body.indices, body.indices[1:]))
        if not in_order or body.indices[0] < 0 or body.indices[-1] >= len(words):
            raise HTTPException(422, "Those caption words no longer exist; reload the captions")
        updated = apply_text_edit(words, body.indices, body.text)
        edits = CaptionEdits.load(conn, clip_id) or CaptionEdits([], [])
        # Edits in parts that are trimmed off for now are kept for when the clip is extended again.
        outside = [w for w in edits.words if not in_clip(w, clip["start_ms"], clip["end_ms"])]
        updated = sorted(outside + updated, key=lambda w: w["start"])
        CaptionEdits(updated, edits.with_range(clip["start_ms"], clip["end_ms"])).save(conn, clip_id)
        conn.execute("UPDATE clips SET status = 'kept' WHERE id = ? AND status = 'suggested'", (clip_id,))
        full = clips.get(conn, clip_id)
    request.app.state.events.emit("clip", full)
    return _captions_payload(request, clip_id)


@router.delete("/clips/{clip_id}/captions")
def reset_captions(clip_id: int, request: Request) -> dict[str, Any]:
    """Throw away edits and go back to the transcript."""
    with request.app.state.db.connect() as conn:
        _clip_or_404(conn, clip_id)
        conn.execute("DELETE FROM clip_captions WHERE clip_id = ?", (clip_id,))
    return _captions_payload(request, clip_id)


@router.post("/sources/{source_id}/transcribe", status_code=202)
def transcribe_source(source_id: int, body: TranscribeRequest, request: Request) -> dict[str, Any]:
    manager = request.app.state.analysis
    with request.app.state.db.connect() as conn:
        src = conn.execute("SELECT status FROM sources WHERE id = ?", (source_id,)).fetchone()
    if src is None:
        raise HTTPException(404, "Source not found")
    if src["status"] != "ready":
        raise HTTPException(409, "This video is still importing")
    try:
        return manager.submit(source_id, {"mode": "transcribe", "model": body.model, "language": body.language})
    except AlreadyRunning:
        raise HTTPException(409, "This video is already being analyzed") from None
