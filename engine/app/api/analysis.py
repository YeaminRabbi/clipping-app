import json
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, model_validator

from .. import clips, sources
from ..analysis import manager as analyses
from ..analysis.finder import next_alternate
from ..analysis.transcribe import MODELS

router = APIRouter(tags=["analysis"])


class AnalyzeRequest(BaseModel):
    mode: Literal["talking", "action", "even"] = "talking"
    clip_count: int | None = Field(default=None, ge=1, le=50)  # None = automatic
    min_seconds: float = Field(default=15, ge=3, le=180)
    max_seconds: float = Field(default=60, ge=3, le=180)
    keywords: list[str] = Field(default_factory=list, max_length=20)
    range_start_ms: int | None = Field(default=None, ge=0)
    range_end_ms: int | None = Field(default=None, gt=0)
    model: Literal[MODELS] = "base"  # type: ignore[valid-type]
    language: str | None = Field(default=None, max_length=8)

    @model_validator(mode="after")
    def check(self):
        if self.max_seconds < self.min_seconds:
            raise ValueError("The longest clip length must be at least the shortest")
        if self.range_start_ms is not None and self.range_end_ms is not None and self.range_end_ms <= self.range_start_ms:
            raise ValueError("The part to analyze must end after it starts")
        self.keywords = [k.strip() for k in self.keywords if k.strip()][:20]
        return self


def _source_or_404(conn, source_id: int):
    row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Source not found")
    return row


@router.post("/sources/{source_id}/analyze", status_code=202)
def analyze(source_id: int, body: AnalyzeRequest, request: Request) -> dict[str, Any]:
    manager = request.app.state.analysis
    with request.app.state.db.connect() as conn:
        src = _source_or_404(conn, source_id)
    if src["status"] != "ready":
        raise HTTPException(409, "This video is still importing")
    if manager.is_running(source_id):
        raise HTTPException(409, "Clips are already being found for this video")
    span_s = ((body.range_end_ms or src["duration_ms"]) - (body.range_start_ms or 0)) / 1000
    if span_s < body.min_seconds:
        raise HTTPException(422, "The part to analyze is shorter than the shortest clip length")
    return manager.submit(source_id, body.model_dump())


@router.get("/sources/{source_id}/analysis")
def get_analysis(source_id: int, request: Request) -> dict[str, Any] | None:
    with request.app.state.db.connect() as conn:
        _source_or_404(conn, source_id)
        return analyses.get(conn, source_id)


@router.get("/projects/{project_id}/analyses")
def list_analyses(project_id: int, request: Request) -> list[dict[str, Any]]:
    with request.app.state.db.connect() as conn:
        rows = conn.execute(
            "SELECT a.* FROM analyses a JOIN sources s ON s.id = a.source_id WHERE s.project_id = ?", (project_id,)
        ).fetchall()
    return [analyses.to_dict(r) for r in rows]


@router.post("/sources/{source_id}/analysis/cancel")
def cancel_analysis(source_id: int, request: Request) -> dict[str, Any]:
    if not request.app.state.analysis.cancel(source_id):
        raise HTTPException(409, "Clips are not being found for this video")
    with request.app.state.db.connect() as conn:
        return analyses.get(conn, source_id)


@router.get("/sources/{source_id}/transcript")
def get_transcript(source_id: int, request: Request) -> dict[str, Any]:
    with request.app.state.db.connect() as conn:
        src = _source_or_404(conn, source_id)
    path = sources.source_dir(request.app.state.settings, src["project_id"], source_id) / "transcript.json"
    if not path.is_file():
        raise HTTPException(404, "This video hasn't been transcribed yet")
    return json.loads(Path(path).read_text(encoding="utf-8"))


@router.post("/clips/{clip_id}/replace")
def replace_clip(clip_id: int, request: Request) -> dict[str, Any]:
    """Swap a clip for the next-best moment from the last analysis."""
    with request.app.state.db.connect() as conn:
        clip = clips.get(conn, clip_id)
        if clip is None:
            raise HTTPException(404, "Clip not found")
        row = conn.execute("SELECT result_json FROM analyses WHERE source_id = ?", (clip["source_id"],)).fetchone()
        if row is None or not row["result_json"]:
            raise HTTPException(409, "Find clips automatically first, then you can replace them")
        result = json.loads(row["result_json"])
        others = conn.execute(
            "SELECT start_ms, end_ms FROM clips WHERE source_id = ? AND id != ?", (clip["source_id"], clip_id)
        ).fetchall()
        # A replacement must be a different moment: skip anything overlapping a clip already shown,
        # including this one, not just the same window stretched by a sentence.
        shown = [tuple(s) for s in result.get("shown", [])] + [(clip["start_ms"], clip["end_ms"])]
        taken = [(r["start_ms"], r["end_ms"]) for r in others] + shown
        alt = next_alternate(result["pool"], taken, set(shown))
        if alt is None:
            raise HTTPException(409, "No other good moments are left. Try different settings to find more.")
        conn.execute("DELETE FROM clips WHERE id = ?", (clip_id,))
        cur = conn.execute(
            """INSERT INTO clips (source_id, start_ms, end_ms, title, status, score, score_reasons_json, sort_order, created_at)
               VALUES (?, ?, ?, ?, 'suggested', ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))""",
            (clip["source_id"], alt["start"], alt["end"], alt["title"] or clip["title"], alt["score"],
             json.dumps(alt["reasons"]), clip["sort_order"]),
        )  # fmt: skip
        result["shown"] = [*result.get("shown", []), [alt["start"], alt["end"]]]
        conn.execute(
            "UPDATE analyses SET result_json = ? WHERE source_id = ?", (json.dumps(result), clip["source_id"])
        )
        new_clip = clips.get(conn, cur.lastrowid)
    events = request.app.state.events
    events.emit("clip_deleted", {"id": clip_id, "source_id": clip["source_id"]})
    events.emit("clip", new_clip)
    return new_clip
