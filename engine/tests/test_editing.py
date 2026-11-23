"""Clips, framing, timeline assets and export, run against the real bundled FFmpeg."""

import json
import subprocess
import time
from fractions import Fraction
from pathlib import Path

import pytest

from app.aspects import crop_pixels, default_crop, output_size
from app.exports import render_name
from app.media.render import output_frame_count, trim_window
from conftest import FFMPEG, FFPROBE, needs_ffmpeg, wait_for

# --- pure geometry / naming -------------------------------------------------------------------


def test_output_sizes():
    assert output_size("9:16") == (1080, 1920)
    assert output_size("4:5") == (1080, 1350)
    assert output_size("1:1", 720) == (720, 720)
    assert output_size("16:9") == (1920, 1080)
    assert output_size("4:3") == (1440, 1080)


def test_default_crop_is_centered_and_full_height():
    crop = default_crop("9:16", 1920, 1080)
    assert crop["h"] == 1 and crop["y"] == 0
    assert crop["x"] == pytest.approx((1 - crop["w"]) / 2)
    assert crop["w"] * 1920 / 1080 == pytest.approx(9 / 16)


def test_crop_pixels_even_inside_frame_and_exact_aspect():
    w, h, x, y = crop_pixels({"x": 0.9, "y": 0, "w": 0.4, "h": 1}, "9:16", 1920, 1080)
    assert all(v % 2 == 0 for v in (w, h, x, y))
    assert x + w <= 1920 and y + h <= 1080
    assert abs(w / h - 9 / 16) < 0.01


def test_trim_window_selects_exact_frames():
    seek, duration = trim_window(1000, 2000, "30")
    assert seek == pytest.approx(29.5 / 30)
    assert duration == 1
    # Milliseconds that aren't on a frame boundary snap to the nearest frame.
    seek, duration = trim_window(1033, 1967, "30000/1001")
    assert duration * Fraction(30000, 1001) == 28
    assert output_frame_count(trim_window(2000, 8067, "30")[1], "30") == 182
    assert output_frame_count(trim_window(2000, 8067, "30")[1], "60") == 364


def test_render_name_sanitizes():
    name = render_name("{project}_{index}_{title}_{ratio}", project="My: Show", index="01", title='Big "win"?', ratio="9x16")
    assert name == "My Show_01_Big win_9x16"
    assert render_name("{nope}", project="x") == "{nope}"
    assert render_name("{title}", title="Let me tell you the biggest…") == "Let me tell you the biggest"


# --- API ---------------------------------------------------------------------------------------


@pytest.fixture
def ready_source(client, project, short_video) -> dict:
    sid = client.post(f"/projects/{project['id']}/sources", json={"path": str(short_video)}).json()["id"]
    source = wait_for(client, sid, {"ready", "failed"})
    assert source["status"] == "ready", source["error"]
    return source


@needs_ffmpeg
def test_timeline_assets(client, ready_source, tmp_path):
    tl = ready_source["timeline"]
    assert tl["peaks_per_second"] == 100
    waveform = client.get(tl["waveform_url"]).content
    assert 290 <= len(waveform) <= 310 and max(waveform) == 255

    thumbs = client.get(tl["thumbs_url"])
    assert thumbs.status_code == 200 and thumbs.headers["content-type"] == "image/jpeg"
    layout = tl["thumbs"]
    assert layout["count"] == 3 and layout["tile_h"] == 90 and layout["tile_w"] == 160

    # Every tile, including the last, holds a real frame rather than black padding.
    sprite = tmp_path / "thumbs.jpg"
    sprite.write_bytes(thumbs.content)
    for i in range(layout["count"]):
        x = (i % layout["cols"]) * layout["tile_w"]
        y = (i // layout["cols"]) * layout["tile_h"]
        rgb = subprocess.run(
            [FFMPEG, "-v", "error", "-i", str(sprite), "-vf", f"crop={layout['tile_w']}:{layout['tile_h']}:{x}:{y},scale=1:1",
             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            capture_output=True, check=True,
        ).stdout  # fmt: skip
        assert sum(rgb) > 60, f"thumbnail {i} is blank"


@needs_ffmpeg
def test_clip_crud_and_validation(client, ready_source):
    sid = ready_source["id"]
    clip = client.post(f"/sources/{sid}/clips", json={"start_ms": 500, "end_ms": 1500}).json()
    assert clip["title"] == "Clip 1" and clip["status"] == "kept" and clip["formats"] == {}

    assert client.post(f"/sources/{sid}/clips", json={"start_ms": 500, "end_ms": 550}).status_code == 422
    assert client.post(f"/sources/{sid}/clips", json={"start_ms": 0, "end_ms": 99_000}).status_code == 422

    clip = client.patch(f"/clips/{clip['id']}", json={"end_ms": 2000, "title": "Hook"}).json()
    assert (clip["start_ms"], clip["end_ms"], clip["title"]) == (500, 2000, "Hook")
    assert client.patch(f"/clips/{clip['id']}", json={"start_ms": 2500}).status_code == 422

    crop = {"x": 0.1, "y": 0, "w": 0.3, "h": 1}
    clip = client.put(f"/clips/{clip['id']}/formats/9x16", json={"mode": "manual", "crop": crop}).json()
    assert clip["formats"]["9:16"]["crop"] == crop
    clip = client.put(f"/clips/{clip['id']}/formats/9:16", json={"mode": "fit"}).json()
    assert clip["formats"]["9:16"]["mode"] == "fit"
    assert client.put(f"/clips/{clip['id']}/formats/9:16", json={"mode": "manual"}).status_code == 422
    assert client.put(f"/clips/{clip['id']}/formats/2:1", json={"mode": "fit"}).status_code == 404
    bad = {"x": 0.8, "y": 0, "w": 0.3, "h": 1}
    assert client.put(f"/clips/{clip['id']}/formats/9:16", json={"mode": "manual", "crop": bad}).status_code == 422

    assert [c["id"] for c in client.get(f"/sources/{sid}/clips").json()] == [clip["id"]]
    assert client.delete(f"/clips/{clip['id']}").status_code == 204
    assert client.get(f"/sources/{sid}/clips").json() == []


def _wait_export(client, project_id: int, job_ids: set[int], timeout: float = 120) -> list[dict]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        jobs = [j for j in client.get(f"/projects/{project_id}/exports").json() if j["id"] in job_ids]
        if all(j["status"] in ("done", "failed", "cancelled") for j in jobs):
            return jobs
        time.sleep(0.2)
    raise AssertionError("exports did not finish")


def _probe(path: str) -> dict:
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
         "stream=width,height,nb_read_frames,codec_name,r_frame_rate", "-of", "json", path],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    return json.loads(out)["streams"][0]


def _preset(tmp_path: Path, **overrides) -> dict:
    return {"output_dir": str(tmp_path / "out"), "hardware": False, "default_framing": "center", **overrides}


@needs_ffmpeg
def test_export_crop_and_fit(client, project, ready_source, tmp_path):
    sid = ready_source["id"]
    clip = client.post(f"/sources/{sid}/clips", json={"start_ms": 1000, "end_ms": 2000, "title": "Best bit"}).json()
    client.put(f"/clips/{clip['id']}/formats/1:1", json={"mode": "fit"})

    jobs = client.post(
        "/exports", json={"clip_ids": [clip["id"]], "aspects": ["9:16", "1:1"], "preset": _preset(tmp_path)}
    ).json()
    assert [j["output_name"] for j in jobs] == ["Test_01_Best bit_9x16", "Test_01_Best bit_1x1"]

    done = {j["aspect"]: j for j in _wait_export(client, project["id"], {j["id"] for j in jobs})}
    assert all(j["status"] == "done" for j in done.values()), [j["error"] for j in done.values()]
    assert done["9:16"]["mode"] == "manual" and done["1:1"]["mode"] == "fit"
    assert done["9:16"]["encoder"] == "libx264"

    portrait = _probe(done["9:16"]["output_path"])
    assert (portrait["width"], portrait["height"]) == (1080, 1920)
    assert int(portrait["nb_read_frames"]) == 30  # exactly 1.000 s at 30 fps
    square = _probe(done["1:1"]["output_path"])
    assert (square["width"], square["height"]) == (1080, 1080)

    # Re-exporting never overwrites an earlier file.
    again = client.post("/exports", json={"clip_ids": [clip["id"]], "aspects": ["9:16"], "preset": _preset(tmp_path)}).json()
    redo = _wait_export(client, project["id"], {again[0]["id"]})[0]
    assert redo["output_path"].endswith("Test_01_Best bit_9x16 (2).mp4")


@needs_ffmpeg
def test_export_options_hevc_720_60fps(client, project, ready_source, tmp_path):
    clip = client.post(f"/sources/{ready_source['id']}/clips", json={"start_ms": 0, "end_ms": 1000}).json()
    preset = _preset(tmp_path, codec="hevc", resolution=720, fps="60", quality="small", name_template="{title}")
    jobs = client.post("/exports", json={"clip_ids": [clip["id"]], "aspects": ["16:9"], "preset": preset}).json()
    job = _wait_export(client, project["id"], {jobs[0]["id"]})[0]
    assert job["status"] == "done", job["error"]
    info = _probe(job["output_path"])
    assert (info["codec_name"], info["width"], info["height"]) == ("hevc", 1280, 720)
    assert info["r_frame_rate"] == "60/1" and int(info["nb_read_frames"]) == 60


@needs_ffmpeg
@pytest.mark.parametrize("fps, expected", [("source", 32), ("60", 64)])
def test_odd_length_clip_has_exact_frame_count(client, project, ready_source, tmp_path, fps, expected):
    # 500 -> 1567 ms is frames 15 -> 47; a rounded printed duration used to let a 33rd frame in.
    clip = client.post(f"/sources/{ready_source['id']}/clips", json={"start_ms": 500, "end_ms": 1567}).json()
    jobs = client.post(
        "/exports", json={"clip_ids": [clip["id"]], "aspects": ["16:9"], "preset": _preset(tmp_path, fps=fps, resolution=720)}
    ).json()
    job = _wait_export(client, project["id"], {jobs[0]["id"]})[0]
    assert job["status"] == "done", job["error"]
    assert int(_probe(job["output_path"])["nb_read_frames"]) == expected


@needs_ffmpeg
def test_export_with_hardware_encoder_if_available(client, project, ready_source, tmp_path):
    clip = client.post(f"/sources/{ready_source['id']}/clips", json={"start_ms": 0, "end_ms": 1000}).json()
    jobs = client.post(
        "/exports", json={"clip_ids": [clip["id"]], "aspects": ["9:16"], "preset": _preset(tmp_path, hardware=True)}
    ).json()
    job = _wait_export(client, project["id"], {jobs[0]["id"]})[0]
    assert job["status"] == "done", job["error"]
    assert int(_probe(job["output_path"])["nb_read_frames"]) == 30


@needs_ffmpeg
def test_cut_lands_on_the_exact_frame(client, project, tmp_path):
    # Red for exactly 30 frames, then blue: a cut at 1000 ms must start on the first blue frame.
    src = tmp_path / "redblue.mp4"
    subprocess.run(
        [FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "color=red:s=320x240:r=30:d=1",
         "-f", "lavfi", "-i", "color=blue:s=320x240:r=30:d=1",
         "-filter_complex", "[0:v][1:v]concat=n=2:v=1[v]", "-map", "[v]", "-c:v", "libx264", "-g", "60", str(src)],
        check=True,
    )  # fmt: skip
    sid = client.post(f"/projects/{project['id']}/sources", json={"path": str(src)}).json()["id"]
    wait_for(client, sid, {"ready"})
    red = client.post(f"/sources/{sid}/clips", json={"start_ms": 0, "end_ms": 1000}).json()
    blue = client.post(f"/sources/{sid}/clips", json={"start_ms": 1000, "end_ms": 2000}).json()
    jobs = client.post(
        "/exports", json={"clip_ids": [red["id"], blue["id"]], "aspects": ["4:3"], "preset": _preset(tmp_path)}
    ).json()
    done = {j["clip_id"]: j for j in _wait_export(client, project["id"], {j["id"] for j in jobs})}

    def frame_rgb(path: str, which: str) -> tuple[int, int, int]:
        select = ["-vf", "scale=1:1", "-frames:v", "1"] if which == "first" else ["-sseof", "-0.05", "-vf", "scale=1:1"]
        args = [FFMPEG, "-v", "error", *(select[:2] if which == "last" else []), "-i", path]
        args += select[2:] if which == "last" else select
        args += ["-f", "rawvideo", "-pix_fmt", "rgb24", "-update", "1", "-"]
        data = subprocess.run(args, capture_output=True, check=True).stdout[-3:]
        return tuple(data)

    r, g, b = frame_rgb(done[red["id"]]["output_path"], "last")
    assert r > 200 and b < 60, "red clip must not include a blue frame"
    r, g, b = frame_rgb(done[blue["id"]]["output_path"], "first")
    assert b > 200 and r < 60, "blue clip must not start on a red frame"
    for job in done.values():
        assert int(_probe(job["output_path"])["nb_read_frames"]) == 30


@needs_ffmpeg
def test_cancel_export_and_clear_finished(client, project, tmp_path):
    from conftest import make_video

    src = make_video(tmp_path / "long.mp4", 20, size="1920x1080")
    sid = client.post(f"/projects/{project['id']}/sources", json={"path": str(src)}).json()["id"]
    wait_for(client, sid, {"ready"}, timeout=120)
    clip = client.post(f"/sources/{sid}/clips", json={"start_ms": 0, "end_ms": 20000}).json()
    job = client.post(
        "/exports", json={"clip_ids": [clip["id"]], "aspects": ["16:9"], "preset": _preset(tmp_path)}
    ).json()[0]
    deadline = time.monotonic() + 30
    while client.get(f"/projects/{project['id']}/exports").json()[0]["status"] != "rendering":
        assert time.monotonic() < deadline
        time.sleep(0.05)
    assert client.post(f"/exports/{job['id']}/cancel").status_code == 200
    job = _wait_export(client, project["id"], {job["id"]})[0]
    assert job["status"] == "cancelled"
    assert not list((tmp_path / "out").glob("*.partial.mp4"))

    assert client.delete(f"/projects/{project['id']}/exports").status_code == 204
    assert client.get(f"/projects/{project['id']}/exports").json() == []
