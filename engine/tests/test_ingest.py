"""End-to-end import tests. They run the real bundled FFmpeg on small generated videos."""

import functools
import http.server
import subprocess
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from conftest import BIN_DIR, FFMPEG, TOKEN, make_video, needs_ffmpeg, wait_for

pytestmark = needs_ffmpeg


def test_file_import_probes_and_builds_proxy(client, project, short_video):
    res = client.post(f"/projects/{project['id']}/sources", json={"path": str(short_video)})
    assert res.status_code == 201
    assert res.json()["title"] == "sample clip.mp4"

    source = wait_for(client, res.json()["id"], {"ready", "failed"})
    assert source["status"] == "ready", source["error"]
    assert (source["width"], source["height"], source["fps"]) == (1280, 720, 30)
    assert 2900 <= source["duration_ms"] <= 3100
    assert source["has_audio"] and source["progress"] == 1
    assert source["proxy_url"] and source["poster_url"]

    # Media accepts the token as a query parameter and supports range requests for seeking.
    del client.headers["x-engine-token"]
    proxy = client.get(source["proxy_url"], params={"token": TOKEN}, headers={"range": "bytes=0-99"})
    client.headers["x-engine-token"] = TOKEN
    assert proxy.status_code == 206 and len(proxy.content) == 100
    assert client.get(source["poster_url"], headers={"x-engine-token": "bad"}).status_code == 401

    # The proxy is 480p at the source's frame rate.
    proxy_path = Path(client.app.state.ingest.source_dir(project["id"], source["id"])) / "proxy.mp4"
    out = subprocess.run([FFMPEG, "-i", str(proxy_path)], capture_output=True, text=True).stderr
    assert "854x480" in out and "30 fps" in out

    assert client.get(f"/projects/{project['id']}").json()["source_count"] == 1


def test_link_import(client, project, short_video):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(short_video.parent))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/sample%20clip.mp4"
        res = client.post(f"/projects/{project['id']}/sources", json={"url": url})
        source = wait_for(client, res.json()["id"], {"ready", "failed"})
    finally:
        server.shutdown()
    assert source["status"] == "ready", source["error"]
    assert source["origin"] == "url" and source["title"]
    assert Path(source["path"]).parent == client.app.state.ingest.source_dir(project["id"], source["id"])


def test_non_video_file_fails_with_message(client, project, tmp_path):
    bogus = tmp_path / "notes.mp4"
    bogus.write_text("not a video")
    res = client.post(f"/projects/{project['id']}/sources", json={"path": str(bogus)})
    source = wait_for(client, res.json()["id"], {"ready", "failed"})
    assert source["status"] == "failed"
    assert "Not a readable video" in source["error"]


@pytest.mark.parametrize(
    "body",
    [{"url": "ftp://example.com/a.mp4"}, {"url": "not a link"}, {"path": "relative.mp4"}, {"path": "C:/nope/missing.mp4"}, {}],
)
def test_invalid_input_rejected(client, project, body):
    assert client.post(f"/projects/{project['id']}/sources", json=body).status_code == 422


def test_cancel_then_retry(client, project, tmp_path):
    video = make_video(tmp_path / "long.mp4", 40, size="1920x1080")
    sid = client.post(f"/projects/{project['id']}/sources", json={"path": str(video)}).json()["id"]
    wait_for(client, sid, {"processing"})
    assert client.post(f"/sources/{sid}/cancel").status_code == 200
    source = wait_for(client, sid, {"cancelled", "ready", "failed"})
    assert source["status"] == "cancelled"
    assert client.post(f"/sources/{sid}/cancel").status_code == 409

    assert client.post(f"/sources/{sid}/retry").status_code == 200
    assert wait_for(client, sid, {"ready", "failed"}, timeout=120)["status"] == "ready"


def test_delete_source_keeps_users_file(client, project, short_video):
    sid = client.post(f"/projects/{project['id']}/sources", json={"path": str(short_video)}).json()["id"]
    wait_for(client, sid, {"ready", "failed"})
    work_dir = client.app.state.ingest.source_dir(project["id"], sid)
    assert work_dir.is_dir()

    assert client.delete(f"/sources/{sid}").status_code == 204
    assert not work_dir.exists()
    assert short_video.is_file()
    assert client.get(f"/sources/{sid}").status_code == 404


def test_interrupted_imports_marked_failed_on_startup(tmp_path):
    settings = Settings(data_dir=tmp_path, token=TOKEN, bin_dir=BIN_DIR)
    with TestClient(create_app(settings), headers={"x-engine-token": TOKEN}) as c:
        pid = c.post("/projects", json={"name": "P"}).json()["id"]
        with c.app.state.db.connect() as conn:
            conn.execute("INSERT INTO sources (project_id, origin, path, status) VALUES (?, 'file', 'x', 'processing')", (pid,))  # fmt: skip
    with TestClient(create_app(settings), headers={"x-engine-token": TOKEN}) as c:
        source = c.get(f"/projects/{pid}/sources").json()[0]
        assert source["status"] == "failed" and "interrupted" in source["error"]
