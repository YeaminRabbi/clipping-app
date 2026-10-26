import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

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
    assert body["db"]["schema_version"] == 1
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
