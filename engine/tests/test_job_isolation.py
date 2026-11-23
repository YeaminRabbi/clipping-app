"""A deleted or cancelled job must never change another job (F-04). No FFmpeg needed: rendering and
probing are replaced by functions the test holds open."""

import sqlite3
import threading
import time
from types import SimpleNamespace

import pytest

from app import db as db_module
from app.db import MIGRATIONS, Database
from app.media import CancelToken, Cancelled, MediaError

TOOLS = SimpleNamespace(
    ffmpeg=SimpleNamespace(path="ffmpeg"), ffprobe=SimpleNamespace(path="ffprobe"), ok=True, hw_encoders={}
)


def eventually(check, timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    while not (result := check()):
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.02)
    return result


@pytest.fixture
def source_id(client, project, tmp_path) -> int:
    video = tmp_path / "video.mp4"
    video.write_bytes(b"x")
    with client.app.state.db.connect() as conn:
        return conn.execute(
            """INSERT INTO sources (project_id, origin, path, status, duration_ms, fps, width, height, has_audio, proxy_path)
               VALUES (?, 'file', ?, 'ready', 20000, 30, 1920, 1080, 0, 'p.mp4')""",
            (project["id"], str(video)),
        ).lastrowid


class Renders:
    """Stands in for render_clip: each export waits until the test lets it go."""

    def __init__(self):
        self.open: set[str] = set()

    def __call__(self, ffmpeg, src, dest, *, cancel, **kwargs):
        while not any(name in dest.name for name in self.open):
            if cancel.cancelled:
                raise Cancelled()
            time.sleep(0.01)
        dest.write_bytes(b"video")


@pytest.fixture
def renders(monkeypatch) -> Renders:
    fake = Renders()
    monkeypatch.setattr("app.ffmpeg.detect", lambda bin_dir: TOOLS)
    monkeypatch.setattr("app.exports.render_clip", fake)
    monkeypatch.setattr(
        "app.exports.probe",
        lambda ffprobe, path: SimpleNamespace(
            fps_rational="30/1", width=1920, height=1080, has_audio=False, video_offset_s=0.0, container="mov,mp4"
        ),
    )
    return fake


def make_clip(client, source_id: int, title: str) -> int:
    return client.post(f"/sources/{source_id}/clips", json={"start_ms": 0, "end_ms": 900, "title": title}).json()["id"]


def export(client, tmp_path, clip_ids: list[int], **preset) -> list[dict]:
    preset = {"output_dir": str(tmp_path / "out"), "default_framing": "center", "hardware": False, "name_template": "{title}", **preset}
    res = client.post("/exports", json={"clip_ids": clip_ids, "aspects": ["9:16"], "preset": preset})
    assert res.status_code == 201, res.text
    return res.json()


def status_of(client, project, job_id: int) -> str:
    return next(j["status"] for j in client.get(f"/projects/{project['id']}/exports").json() if j["id"] == job_id)


# --- ids -----------------------------------------------------------------------------------------


def test_ids_are_never_reused(client, project, source_id, tmp_path):
    clip = make_clip(client, source_id, "a")
    client.delete(f"/clips/{clip}")
    assert make_clip(client, source_id, "b") > clip
    client.delete(f"/sources/{source_id}")
    video = tmp_path / "other.mp4"
    video.write_bytes(b"x")
    new = client.post(f"/projects/{project['id']}/sources", json={"path": str(video)}).json()
    assert new["id"] > source_id
    client.delete(f"/projects/{project['id']}")
    assert client.post("/projects", json={"name": "next"}).json()["id"] > project["id"]


def test_migration_keeps_everything_and_its_links(tmp_path, monkeypatch):
    """A database from before ids were unique, with a row in every rebuilt table."""
    path = tmp_path / "old.db"
    monkeypatch.setattr(db_module, "MIGRATIONS", MIGRATIONS[:7])
    Database(path).migrate()
    with Database(path).connect() as conn:
        conn.execute("INSERT INTO projects (id, name) VALUES (3, 'P')")
        conn.execute("INSERT INTO sources (id, project_id, origin, title, status) VALUES (5, 3, 'file', 'S', 'ready')")
        conn.execute("INSERT INTO clips (id, source_id, start_ms, end_ms, title, edit_json) VALUES (7, 5, 0, 10, 'C', '{\"a\":1}')")
        conn.execute("INSERT INTO clip_formats (id, clip_id, aspect, options_json) VALUES (9, 7, '9:16', '{\"b\":2}')")
        conn.execute("INSERT INTO export_jobs (id, clip_format_id, output_name, batch_id) VALUES (11, 9, 'n', 'x')")
        conn.execute("INSERT INTO clip_captions (clip_id, words_json) VALUES (7, '[]')")
        conn.execute("INSERT INTO analyses (source_id) VALUES (5)")
    monkeypatch.setattr(db_module, "MIGRATIONS", MIGRATIONS)
    assert Database(path).migrate() == len(MIGRATIONS)
    with Database(path).connect() as conn:
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        assert conn.execute("SELECT title FROM sources WHERE id = 5").fetchone()[0] == "S"
        assert conn.execute("SELECT edit_json FROM clips WHERE id = 7").fetchone()[0] == '{"a":1}'
        assert conn.execute("SELECT options_json FROM clip_formats WHERE id = 9").fetchone()[0] == '{"b":2}'
        assert conn.execute("SELECT output_name FROM export_jobs WHERE id = 11").fetchone()[0] == "n"
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO clip_formats (clip_id, aspect) VALUES (7, '9:16')")
        # Deleting still reaches everything below.
        conn.execute("DELETE FROM projects WHERE id = 3")
        for table in ("sources", "clips", "clip_formats", "export_jobs", "clip_captions", "analyses"):
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0, table


# --- imports -------------------------------------------------------------------------------------


def test_deleting_a_running_import_and_adding_another_keeps_them_apart(client, project, tmp_path, monkeypatch):
    gates = {"old.mp4": threading.Event(), "new.mp4": threading.Event()}

    def probe(ffprobe, path):
        gates[path.name].wait(10)
        raise MediaError(f"error from {path.name}")

    monkeypatch.setattr("app.ffmpeg.detect", lambda bin_dir: TOOLS)
    monkeypatch.setattr("app.ingest.probe", probe)
    ingest = client.app.state.ingest
    files = {}
    for name in gates:
        (tmp_path / name).write_bytes(b"x")
    add = lambda name: client.post(f"/projects/{project['id']}/sources", json={"path": str(tmp_path / name)}).json()["id"]
    old = add("old.mp4")
    eventually(lambda: client.get(f"/sources/{old}").json()["status"] == "probing")
    client.delete(f"/sources/{old}")
    new = add("new.mp4")
    eventually(lambda: client.get(f"/sources/{new}").json()["status"] == "probing")
    assert new != old and ingest.source_dir(project["id"], new) != ingest.source_dir(project["id"], old)
    marker = ingest.source_dir(project["id"], new) / "marker"
    marker.write_text("mine")

    gates["old.mp4"].set()  # the deleted import's worker now fails and cleans up
    eventually(lambda: old not in ingest.tokens)
    eventually(lambda: not ingest.source_dir(project["id"], old).exists())
    source = client.get(f"/sources/{new}").json()
    assert (source["status"], source["error"]) == ("probing", None)
    assert marker.read_text() == "mine"

    gates["new.mp4"].set()
    eventually(lambda: client.get(f"/sources/{new}").json()["status"] == "failed")
    assert client.get(f"/sources/{new}").json()["error"] == "error from new.mp4"


def test_a_worker_that_lost_its_job_cannot_write(client, project, source_id):
    ingest = client.app.state.ingest
    current, stale = CancelToken(), CancelToken()
    ingest.tokens[source_id] = current
    assert ingest._update(source_id, stale, status="cancelled", error="stale") is None
    assert client.get(f"/sources/{source_id}").json()["status"] == "ready"
    assert ingest._update(source_id, current, title="new title")["title"] == "new title"
    del ingest.tokens[source_id]


def test_retrying_an_import_twice_starts_it_once(client, project, source_id):
    started = []
    client.app.state.ingest.submit = lambda source: started.append(source["id"])
    with client.app.state.db.connect() as conn:
        conn.execute("UPDATE sources SET status = 'failed' WHERE id = ?", (source_id,))
    codes = [client.post(f"/sources/{source_id}/retry").status_code for _ in range(2)]
    assert codes == [200, 409] and started == [source_id]


# --- exports -------------------------------------------------------------------------------------


def test_deleting_a_queued_export_and_adding_another_keeps_them_apart(client, project, source_id, tmp_path, renders):
    manager = client.app.state.exports
    # Fill both workers, queue a third, delete its clip, then start a new export.
    busy = export(client, tmp_path, [make_clip(client, source_id, t) for t in ("busy one", "busy two")])
    doomed_clip = make_clip(client, source_id, "doomed")
    doomed = export(client, tmp_path, [doomed_clip])[0]
    client.delete(f"/clips/{doomed_clip}")
    fresh = export(client, tmp_path, [make_clip(client, source_id, "fresh")])[0]
    assert fresh["id"] != doomed["id"]

    seen: list[str] = []
    original = manager._update

    def record(job_id, token, **fields):
        if job_id == fresh["id"] and "status" in fields:
            seen.append(fields["status"])
        return original(job_id, token, **fields)

    manager._update = record
    renders.open.add("busy")
    eventually(lambda: status_of(client, project, busy[0]["id"]) == "done")
    eventually(lambda: status_of(client, project, fresh["id"]) == "rendering")
    renders.open.add("fresh")
    eventually(lambda: status_of(client, project, fresh["id"]) == "done")
    assert seen == ["rendering", "done"], "never marked cancelled by the deleted job"
    # Reaching the deleted job late changes nothing either.
    token = CancelToken()
    token.cancel()
    manager._run(doomed["id"], token)
    manager._run(fresh["id"], token)
    assert status_of(client, project, fresh["id"]) == "done"


def test_retrying_an_export_twice_starts_it_once(client, project, source_id, tmp_path, renders):
    job = export(client, tmp_path, [make_clip(client, source_id, "x")])[0]
    client.post(f"/exports/{job['id']}/cancel")
    eventually(lambda: status_of(client, project, job["id"]) == "cancelled")
    codes = [client.post(f"/exports/{job['id']}/retry").status_code for _ in range(2)]
    assert codes == [200, 409]
    renders.open.add("x")
    eventually(lambda: status_of(client, project, job["id"]) == "done")


def test_work_folders_are_separate_and_cleared_at_startup(client):
    work = client.app.state.settings.work_dir
    (work / "export-1-abc").mkdir(parents=True)
    client.app.state.exports.start()
    assert not work.exists()
