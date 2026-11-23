import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import MIGRATIONS
from app.main import create_app
from conftest import needs_ffmpeg

TOKEN = "test-token"


@pytest.fixture
def client(tmp_path):
    settings = Settings(data_dir=tmp_path, token=TOKEN, bin_dir=tmp_path / "bin")
    with TestClient(create_app(settings), headers={"x-engine-token": TOKEN}) as c:
        yield c


def test_rejects_missing_token(client):
    res = client.get("/health", headers={"x-engine-token": ""})
    assert res.status_code == 401


def test_rejection_carries_cors_headers(client):
    origin = "http://localhost:5173"
    res = client.get("/projects", headers={"x-engine-token": "wrong", "origin": origin})
    assert res.status_code == 401
    assert res.headers.get("access-control-allow-origin") == origin


def test_health_reports_db_and_ffmpeg(client):
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["db"]["schema_version"] == len(MIGRATIONS)
    assert "ffmpeg" in body and "ok" in body["ffmpeg"]


def test_project_crud(client):
    assert client.get("/projects").json() == []

    created = client.post("/projects", json={"name": "  Podcast ep 12 "}).json()
    assert created["name"] == "Podcast ep 12"
    assert created["source_count"] == 0

    assert [p["id"] for p in client.get("/projects").json()] == [created["id"]]
    assert client.get(f"/projects/{created['id']}").status_code == 200

    assert client.delete(f"/projects/{created['id']}").status_code == 204
    assert client.get(f"/projects/{created['id']}").status_code == 404
    assert client.delete(f"/projects/{created['id']}").status_code == 404


def test_blank_name_rejected(client):
    assert client.post("/projects", json={"name": "   "}).status_code == 422


def test_websocket_requires_token(client):
    with client.websocket_connect(f"/ws?token={TOKEN}") as ws:
        assert ws.receive_json()["event"] == "hello"


def test_ui_show_resolves_project_and_rejects_unknown(client, project):
    shown = client.post("/ui/show", json={"project_id": project["id"]})
    assert shown.status_code == 200
    assert shown.json()["project_id"] == project["id"] and shown.json()["source_id"] is None
    assert client.post("/ui/show", json={"project_id": 9999}).status_code == 404
    assert client.post("/ui/show", json={"source_id": 9999}).status_code == 404
    assert client.post("/ui/show", json={}).status_code == 422


@needs_ffmpeg
def test_ui_show_source_resolves_its_project(client, project, short_video):
    source = client.post(f"/projects/{project['id']}/sources", json={"path": str(short_video)}).json()
    shown = client.post("/ui/show", json={"source_id": source["id"]})
    assert shown.status_code == 200
    assert shown.json()["project_id"] == project["id"] and shown.json()["source_id"] == source["id"]


def test_reserve_path_never_hands_out_the_same_name(tmp_path):
    from app.exports import reserve_path

    first = reserve_path(tmp_path, "clip")
    second = reserve_path(tmp_path, "clip")
    assert first.name == "clip.mp4" and second.name == "clip (2).mp4"
    assert first.is_file() and second.is_file()


def test_second_analysis_of_a_video_is_rejected_while_one_is_queued(client, project):
    from app.analysis.manager import AlreadyRunning

    db = client.app.state.db
    with db.connect() as conn:
        source_id = conn.execute(
            "INSERT INTO sources (project_id, origin, path, status, duration_ms) VALUES (?, 'file', 'x.mp4', 'ready', 60000)",
            (project["id"],),
        ).lastrowid
    manager = client.app.state.analysis

    class Hold:  # keeps the job queued so the second submit sees it
        def submit(self, *args):
            pass

        def shutdown(self, **kwargs):
            pass

    manager.executor = Hold()
    params = {"mode": "even", "min_seconds": 15, "max_seconds": 60}
    manager.submit(source_id, params)
    with pytest.raises(AlreadyRunning):
        manager.submit(source_id, params)
    assert client.post(f"/sources/{source_id}/analyze", json={"mode": "even"}).status_code == 409


def test_startup_removes_files_left_by_an_interrupted_export(client, project, tmp_path):
    out = tmp_path / "exports"
    out.mkdir()
    placeholder = out / "Clip 1_9x16.mp4"
    placeholder.write_bytes(b"")  # reserve_path's empty placeholder
    partial = out / "Clip 1_9x16.partial.mp4"
    partial.write_bytes(b"half a video")
    finished = out / "Other_9x16.mp4"
    finished.write_bytes(b"a real video")  # a finished file with content must never be touched

    db = client.app.state.db
    with db.connect() as conn:
        source_id = conn.execute(
            "INSERT INTO sources (project_id, origin, path, status, duration_ms) VALUES (?, 'file', 'x.mp4', 'ready', 60000)",
            (project["id"],),
        ).lastrowid
        clip_id = conn.execute("INSERT INTO clips (source_id, start_ms, end_ms) VALUES (?, 0, 5000)", (source_id,)).lastrowid
        format_id = conn.execute("INSERT INTO clip_formats (clip_id, aspect) VALUES (?, '9:16')", (clip_id,)).lastrowid
        for path in (placeholder, finished):
            conn.execute(
                "INSERT INTO export_jobs (clip_format_id, status, output_path) VALUES (?, 'rendering', ?)",
                (format_id, str(path)),
            )

    client.app.state.exports.start()  # what the next app launch runs

    assert not placeholder.exists() and not partial.exists()
    assert finished.read_bytes() == b"a real video"
    with db.connect() as conn:
        assert {r[0] for r in conn.execute("SELECT status FROM export_jobs")} == {"failed"}
