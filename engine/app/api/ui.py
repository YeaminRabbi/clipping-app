"""Asking the open app window to show something, for tools that drive the engine (scripts/clip.mjs).

The engine can't control the window directly; it broadcasts a `ui_show` event and the renderer's
store navigates to it.
"""

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(tags=["ui"])


class Show(BaseModel):
    project_id: int | None = None
    # Open this video in the editor (its project is opened first).
    source_id: int | None = None


@router.post("/ui/show")
def show(body: Show, request: Request) -> dict[str, Any]:
    with request.app.state.db.connect() as conn:
        if body.source_id is not None:
            row = conn.execute("SELECT project_id FROM sources WHERE id = ?", (body.source_id,)).fetchone()
            if row is None:
                raise HTTPException(404, f"Source {body.source_id} not found")
            project_id = row["project_id"]
        elif body.project_id is not None:
            if conn.execute("SELECT 1 FROM projects WHERE id = ?", (body.project_id,)).fetchone() is None:
                raise HTTPException(404, f"Project {body.project_id} not found")
            project_id = body.project_id
        else:
            raise HTTPException(422, "Give a project_id or a source_id")
    target = {"project_id": project_id, "source_id": body.source_id}
    request.app.state.events.emit("ui_show", target)
    return {**target, "windows": request.app.state.events.client_count}
