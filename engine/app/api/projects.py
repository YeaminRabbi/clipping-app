import json
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .. import exports

router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    settings: dict[str, Any] = Field(default_factory=dict)


class Project(BaseModel):
    id: int
    name: str
    settings: dict[str, Any]
    created_at: str
    updated_at: str
    source_count: int = 0


def _to_project(row) -> Project:
    return Project(
        id=row["id"],
        name=row["name"],
        settings=json.loads(row["settings_json"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        source_count=row["source_count"],
    )


_SELECT = """
    SELECT p.*, (SELECT COUNT(*) FROM sources s WHERE s.project_id = p.id) AS source_count
    FROM projects p
"""


@router.get("", response_model=list[Project])
def list_projects(request: Request) -> list[Project]:
    with request.app.state.db.connect() as conn:
        rows = conn.execute(_SELECT + " ORDER BY p.updated_at DESC, p.id DESC").fetchall()
    return [_to_project(r) for r in rows]


@router.post("", response_model=Project, status_code=201)
def create_project(body: ProjectCreate, request: Request) -> Project:
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "Project name cannot be blank")
    with request.app.state.db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO projects (name, settings_json) VALUES (?, ?)",
            (name, json.dumps(body.settings)),
        )
        row = conn.execute(_SELECT + " WHERE p.id = ?", (cur.lastrowid,)).fetchone()
    return _to_project(row)


@router.get("/{project_id}", response_model=Project)
def get_project(project_id: int, request: Request) -> Project:
    with request.app.state.db.connect() as conn:
        row = conn.execute(_SELECT + " WHERE p.id = ?", (project_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "Project not found")
    return _to_project(row)


@router.delete("/{project_id}", status_code=204)
def delete_project(project_id: int, request: Request) -> None:
    ingest = request.app.state.ingest
    with request.app.state.db.connect() as conn:
        source_ids = [r["id"] for r in conn.execute("SELECT id FROM sources WHERE project_id = ?", (project_id,))]
        for job_id in exports.active_job_ids(conn, project_id=project_id):
            request.app.state.exports.cancel(job_id)
        cur = conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    if cur.rowcount == 0:
        raise HTTPException(404, "Project not found")
    for source_id in source_ids:
        ingest.cancel(source_id)
        request.app.state.analysis.cancel(source_id)
    # Downloads, proxies and posters live here; users' own files imported in place are elsewhere.
    ingest.remove_files(ingest.project_dir(project_id))
