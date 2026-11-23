"""Auto clipping end to end on a spoken video (Windows text-to-speech) with known scene cuts.

Uses the small "tiny" speech model, cached in .cache/models so it downloads only once.
"""

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import PROJECT_ROOT, Settings
from app.main import create_app
from conftest import BIN_DIR, FFMPEG, MODELS_DIR, SCENE_CUTS_S, TOKEN, needs_ffmpeg, wait_for


pytestmark = [needs_ffmpeg, pytest.mark.skipif(sys.platform != "win32", reason="needs Windows text-to-speech")]


@pytest.fixture
def client(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", token=TOKEN, bin_dir=BIN_DIR, models_dir=MODELS_DIR)
    settings.projects_dir.mkdir(parents=True)
    with TestClient(create_app(settings), headers={"x-engine-token": TOKEN}) as c:
        yield c


@pytest.fixture
def source(client, podcast) -> dict:
    pid = client.post("/projects", json={"name": "Podcast"}).json()["id"]
    sid = client.post(f"/projects/{pid}/sources", json={"path": str(podcast)}).json()["id"]
    src = wait_for(client, sid, {"ready", "failed"}, timeout=120)
    assert src["status"] == "ready", src["error"]
    return src


def analyze(client, source_id: int, timeout: float = 300, **params) -> dict:
    params = {"model": "tiny", **params}
    res = client.post(f"/sources/{source_id}/analyze", json=params)
    assert res.status_code == 202, res.text
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        a = client.get(f"/sources/{source_id}/analysis").json()
        if a["status"] in ("done", "failed", "cancelled"):
            return a
        time.sleep(0.2)
    raise AssertionError("analysis did not finish")


def test_talking_mode_finds_whole_sentences_with_keyword(client, source):
    a = analyze(client, source["id"], mode="talking", clip_count=2, min_seconds=5, max_seconds=16, keywords=["pricing"])
    assert a["status"] == "done", a["error"]
    assert a["clip_count"] == 2 and a["mode_used"] == "talking"

    clips = client.get(f"/sources/{source['id']}/clips").json()
    words = client.get(f"/sources/{source['id']}/transcript").json()["words"]
    assert len(clips) == 2 and all(c["status"] == "suggested" and c["score"] is not None for c in clips)
    assert clips[0]["end_ms"] <= clips[1]["start_ms"], "clips must not overlap"

    for clip in clips:
        # No word is cut in half at either edge.
        for w in words:
            assert not (w["start"] < clip["start_ms"] < w["end"]), f"start cuts '{w['text']}'"
            assert not (w["start"] < clip["end_ms"] < w["end"]), f"end cuts '{w['text']}'"
        inside = [w["text"] for w in words if w["start"] >= clip["start_ms"] and w["end"] <= clip["end_ms"]]
        assert inside[-1].endswith((".", "!", "?")), f"clip should end on a full sentence: {inside}"
        assert 5_000 - 500 <= clip["end_ms"] - clip["start_ms"] <= 16_000 + 1_000

    # Both pricing sections of the script are picked, and the keyword shows up as a reason.
    assert all(any("keyword: pricing" in r for r in c["reasons"]) for c in clips)


def test_replace_rerun_and_kept_clips(client, source):
    analyze(client, source["id"], mode="talking", clip_count=2, min_seconds=5, max_seconds=16)
    clips = client.get(f"/sources/{source['id']}/clips").json()

    replaced = client.post(f"/clips/{clips[0]['id']}/replace")
    assert replaced.status_code == 200, replaced.text
    new = replaced.json()
    # A genuinely different moment, not the same one stretched or trimmed.
    assert new["end_ms"] <= clips[0]["start_ms"] or clips[0]["end_ms"] <= new["start_ms"]
    others = [c for c in client.get(f"/sources/{source['id']}/clips").json() if c["id"] != new["id"]]
    assert all(new["end_ms"] <= o["start_ms"] or o["end_ms"] <= new["start_ms"] for o in others)

    # Editing a suggested clip keeps it; re-running replaces only the untouched suggestions.
    kept = client.patch(f"/clips/{new['id']}", json={"title": "My favourite"}).json()
    assert kept["status"] == "kept"
    analyze(client, source["id"], mode="talking", clip_count=3, min_seconds=5, max_seconds=16)
    after = client.get(f"/sources/{source['id']}/clips").json()
    assert any(c["id"] == kept["id"] and c["title"] == "My favourite" for c in after)
    for c in after:
        if c["id"] != kept["id"]:
            assert c["status"] == "suggested"
            assert c["end_ms"] <= kept["start_ms"] or kept["end_ms"] <= c["start_ms"]


def test_action_mode_detects_cuts_and_snaps_onto_them(client, source):
    a = analyze(client, source["id"], mode="action", clip_count=3, min_seconds=10, max_seconds=15)
    assert a["status"] == "done", a["error"]
    work = Path(client.app.state.ingest.source_dir(source["project_id"], source["id"]))
    cuts = json.loads((work / "scenes.json").read_text())
    assert [round(c / 1000) for c in cuts] == list(SCENE_CUTS_S)

    clips = client.get(f"/sources/{source['id']}/clips").json()
    assert len(clips) == 3
    # An edge near a cut is moved exactly onto it, never left a few frames off.
    for clip in clips:
        for edge in (clip["start_ms"], clip["end_ms"]):
            assert not any(40 < abs(edge - cut) <= 500 for cut in cuts), f"edge {edge} is just off a cut"


def test_even_split_and_range(client, source):
    a = analyze(client, source["id"], mode="even", clip_count=4, min_seconds=5, max_seconds=10,
                range_start_ms=10_000, range_end_ms=50_000)  # fmt: skip
    assert a["status"] == "done", a["error"]
    clips = client.get(f"/sources/{source['id']}/clips").json()
    assert len(clips) == 4
    assert all(10_000 - 500 <= c["start_ms"] and c["end_ms"] <= 50_000 + 500 for c in clips)
    assert [c["title"] for c in clips] == ["Part 1", "Part 2", "Part 3", "Part 4"]


def test_validation(client, source):
    sid = source["id"]
    assert client.post(f"/sources/{sid}/analyze", json={"min_seconds": 30, "max_seconds": 10}).status_code == 422
    assert client.post(f"/sources/{sid}/analyze", json={"clip_count": 0}).status_code == 422
    assert client.post(f"/sources/{sid}/analyze", json={"min_seconds": 50, "range_start_ms": 0, "range_end_ms": 20_000}).status_code == 422
    assert client.post(f"/sources/{sid}/analysis/cancel").status_code == 409
    assert client.post("/sources/9999/analyze", json={}).status_code == 404


def test_transcript_is_cached_between_runs(client, source):
    analyze(client, source["id"], mode="talking", clip_count=1, min_seconds=5, max_seconds=16)
    work = Path(client.app.state.ingest.source_dir(source["project_id"], source["id"]))
    stamp = (work / "transcript.json").stat().st_mtime
    started = time.monotonic()
    analyze(client, source["id"], mode="talking", clip_count=2, min_seconds=5, max_seconds=16)
    assert (work / "transcript.json").stat().st_mtime == stamp
    assert json.loads((work / "transcript.json").read_text())["model"] == "tiny"
    assert time.monotonic() - started < 15
