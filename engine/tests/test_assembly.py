"""Real-media checks for ordered ranges, timed audio and collage imports."""

import subprocess
import time
from pathlib import Path

import numpy as np
import pytest

from app.edit.timemap import TimeMap
from conftest import FFMPEG, needs_ffmpeg, wait_for
from test_tighten import _export, _frame_colors, _durations


def test_timemap_preserves_reordered_and_repeated_sections():
    mapping = TimeMap([(2000, 3000), (0, 1000), (2000, 3000)])
    words = mapping.map_words([{"text": "first", "start": 100, "end": 400}, {"text": "second", "start": 2100, "end": 2400}])
    assert [(w["text"], w["start"]) for w in words] == [("second", 100), ("first", 1100), ("second", 2100)]


@pytest.fixture
def assembly_source(client, project, tmp_path):
    video = tmp_path / "colors.mp4"
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "color=blue:s=320x180:r=30:d=3",
                    "-vf", "drawbox=color=red:t=fill:enable='lt(t,1)'", "-c:v", "libx264", "-preset", "ultrafast", str(video)], check=True)
    source = client.post(f"/projects/{project['id']}/sources", json={"path": str(video)}).json()
    source = wait_for(client, source["id"], {"ready", "failed"})
    assert source["status"] == "ready", source["error"]
    return source


def clip_for(client, source, start=0, end=3000):
    response = client.post(f"/sources/{source['id']}/clips", json={"start_ms": start, "end_ms": end})
    assert response.status_code == 201, response.text
    return response.json()


def with_sound(client, project, source, tmp_path):
    video = tmp_path / "audible.mp4"
    subprocess.run([FFMPEG, "-v", "error", "-y", "-i", source["path"], "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
                    "-c:v", "copy", "-c:a", "aac", "-shortest", str(video)], check=True)
    sid = client.post(f"/projects/{project['id']}/sources", json={"path": str(video)}).json()["id"]
    ready = wait_for(client, sid, {"ready", "failed"})
    assert ready["status"] == "ready", ready["error"]
    return ready


def audio_rms(path, start, end):
    raw = subprocess.run([FFMPEG, "-v", "error", "-ss", str(start), "-i", str(path), "-t", str(end-start),
                          "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.sqrt(np.mean(np.frombuffer(raw, dtype=np.float32) ** 2))


@needs_ffmpeg
@pytest.mark.parametrize("has_sound", [False, True])
def test_sections_persist_validate_and_export_in_playback_order(client, project, assembly_source, tmp_path, has_sound):
    if has_sound:
        assembly_source = with_sound(client, project, assembly_source, tmp_path)
    clip = clip_for(client, assembly_source)
    sections = [{"start_ms": 2000, "end_ms": 3000}, {"start_ms": 0, "end_ms": 1000}, {"start_ms": 2000, "end_ms": 3000}]
    saved = client.patch(f"/clips/{clip['id']}", json={"segments": sections})
    assert saved.status_code == 200, saved.text
    assert client.get(f"/sources/{assembly_source['id']}/clips").json()[0]["segments"] == sections
    plan = client.get(f"/clips/{clip['id']}/cut-plan").json()
    assert plan["segments"] == [[2000, 3000], [0, 1000], [2000, 3000]]
    assert plan["duration_ms"] == 3000
    assert client.patch(f"/clips/{clip['id']}", json={"end_ms": 2000}).status_code == 422
    assert client.patch(f"/clips/{clip['id']}", json={"segments": [{"start_ms": 1000, "end_ms": 999}]}).status_code == 422
    job = _export(client, project["id"], clip["id"], tmp_path / "out", resolution=720)
    colors = _frame_colors(job["output_path"])
    assert len(colors) == 90
    assert colors[:30] == ["blue"] * 30
    assert colors[30:60] == ["red"] * 30
    assert colors[60:] == ["blue"] * 30
    if has_sound:
        durations = _durations(job["output_path"])
        assert durations["audio"] == pytest.approx(durations["video"], abs=0.06)


@needs_ffmpeg
def test_audio_is_copied_authenticated_and_only_plays_in_selected_section(client, project, assembly_source, tmp_path):
    sound = tmp_path / "tone.wav"
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=880:duration=2", str(sound)], check=True)
    asset_response = client.post(f"/projects/{project['id']}/audio", json={"path": str(sound)})
    assert asset_response.status_code == 201, asset_response.text
    asset = asset_response.json()
    sound.unlink()
    assert client.get(asset["url"]).status_code == 200, "managed copy survives moving the original"
    assert client.get(asset["url"], headers={"x-engine-token": ""}).status_code == 401
    clip = clip_for(client, assembly_source)
    layer = {"asset_id": asset["id"], "start_ms": 1000, "end_ms": 2000, "offset_ms": 500, "volume": 0.8, "original_volume": 0}
    response = client.patch(f"/clips/{clip['id']}", json={"audio": [layer]})
    assert response.status_code == 200, response.text
    assert response.json()["audio"] == [layer]
    assert client.patch(f"/clips/{clip['id']}", json={"audio": [{**layer, "end_ms": 4000}]}).status_code == 422
    job = _export(client, project["id"], clip["id"], tmp_path / "out", resolution=720)
    raw = subprocess.run([FFMPEG, "-v", "error", "-i", job["output_path"], "-vn", "-ac", "1", "-ar", "16000", "-f", "f32le", "-"], capture_output=True, check=True).stdout
    samples = np.frombuffer(raw, dtype=np.float32)
    rms = lambda a, b: np.sqrt(np.mean(samples[int(a * 16000):int(b * 16000)] ** 2))
    assert rms(0.1, 0.8) < 0.001 and rms(2.2, 2.8) < 0.001
    assert rms(1.2, 1.8) > 0.02
    durations = _durations(job["output_path"])
    assert durations["audio"] == pytest.approx(durations["video"], abs=0.06)


@needs_ffmpeg
def test_collage_becomes_one_editable_source_and_clip(client, project, assembly_source, tmp_path):
    audible = with_sound(client, project, assembly_source, tmp_path)
    red = clip_for(client, audible, 0, 1000)
    blue = clip_for(client, assembly_source, 2000, 3000)
    response = client.post(f"/projects/{project['id']}/collages", json={"clip_ids": [blue["id"], red["id"]], "title": "Joined", "aspect": "16:9"})
    assert response.status_code == 202, response.text
    source = wait_for(client, response.json()["id"], {"ready", "failed"}, timeout=120)
    assert source["status"] == "ready", source["error"]
    assert source["duration_ms"] == pytest.approx(2000, abs=100)
    assert client.get(f"/projects/{project['id']}/exports").json() == [], "collage internals stay out of the export list"
    colors = _frame_colors(source["path"])
    assert colors[:29] == ["blue"] * 29
    assert colors[-29:] == ["red"] * 29
    assert audio_rms(source["path"], 0.1, 0.8) < 0.001
    assert audio_rms(source["path"], 1.2, 1.8) > 0.02
    for _ in range(20):
        clips = client.get(f"/sources/{source['id']}/clips").json()
        if clips:
            break
        time.sleep(0.05)
    assert len(clips) == 1 and clips[0]["title"] == "Joined"
    assert clips[0]["start_ms"] == 0 and clips[0]["end_ms"] == source["duration_ms"]
    assert client.post(f"/projects/{project['id']}/collages", json={"clip_ids": [red["id"], 999999]}).status_code == 422


@needs_ffmpeg
def test_original_sound_ducks_only_in_the_added_audio_section(client, project, assembly_source, tmp_path):
    audible = with_sound(client, project, assembly_source, tmp_path)
    asset = client.post(f"/projects/{project['id']}/audio", json={"path": audible["path"]}).json()
    clip = clip_for(client, audible)
    layer = {"asset_id": asset["id"], "start_ms": 1000, "end_ms": 2000, "offset_ms": 0, "volume": 0, "original_volume": 0}
    assert client.patch(f"/clips/{clip['id']}", json={"audio": [layer]}).status_code == 200
    job = _export(client, project["id"], clip["id"], tmp_path / "out", resolution=720)
    assert audio_rms(job["output_path"], 0.1, 0.8) > 0.02
    assert audio_rms(job["output_path"], 1.2, 1.8) < 0.001
    assert audio_rms(job["output_path"], 2.2, 2.8) > 0.02
    other = client.post("/projects", json={"name": "Other"}).json()
    assert client.post(f"/projects/{other['id']}/collages", json={"clip_ids": [clip["id"], clip["id"]]}).status_code == 422
