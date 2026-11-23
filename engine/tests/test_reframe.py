"""Smart reframing: tracking logic (unit) and full track + render (end to end).

The end-to-end tests swap the face detector for one that finds a bright square, so the subject's
true position is known exactly and we can check where it lands in the exported frames.
"""

import subprocess
import time

import numpy as np
import pytest

from app.aspects import default_crop
from app.media.render import piecewise_expr
from app.reframe import detect
from app.reframe.detect import Face
from app.reframe.track import camera_path, choose_subject, crop_at
from conftest import FFMPEG, FFPROBE, needs_ffmpeg, wait_for

CROP_9x16 = default_crop("9:16", 1920, 1080)  # w ~0.316, full height


def face(cx: float, cy: float = 0.4, size: float = 0.1) -> Face:
    return Face(x=cx - size / 2, y=cy - size / 2, w=size, h=size, score=0.9)


def samples(positions: list[float | None], step: int = 200, start: int = 0) -> list[tuple[int, Face | None]]:
    return [(start + i * step, face(p) if p is not None else None) for i, p in enumerate(positions)]


# --- unit ----------------------------------------------------------------------------------------


def test_choose_subject_follows_the_same_face():
    a, b = face(0.3, size=0.10), face(0.7, size=0.12)
    picked = choose_subject([(0, [a]), (200, [a, b]), (400, [b, a])])
    assert [round(f.cx, 2) for _, f in picked] == [0.3, 0.3, 0.3]
    # With no previous face, the biggest wins.
    assert choose_subject([(0, [a, b])])[0][1] is b


def test_still_subject_gives_a_locked_off_crop():
    jitter = [0.62 + (0.01 if i % 2 else -0.01) for i in range(30)]
    keyframes, ratio = camera_path(samples(jitter), [], CROP_9x16)
    assert ratio == 1.0
    assert len({round(k.x, 4) for k in keyframes}) == 1, "a talking head shouldn't make the camera drift"
    assert keyframes[0].x == pytest.approx(0.62 - CROP_9x16["w"] / 2, abs=0.01)
    assert keyframes[0].t == 0 and keyframes[-1].t == 29 * 200


def test_moving_subject_is_followed_smoothly_and_simplified():
    positions = [0.2 + 0.6 * i / 59 for i in range(60)]  # slow pan over 12 s
    keyframes, _ = camera_path(samples(positions), [], CROP_9x16)
    xs = [k.x for k in keyframes]
    assert xs == sorted(xs), "path should move one way"
    assert len(keyframes) < 20, "straight-ish motion collapses to few keyframes"
    w = CROP_9x16["w"]
    for k in keyframes:
        assert 0 <= k.x <= 1 - w
    mid = crop_at([k.as_dict() for k in keyframes], 6000)
    assert mid["x"] + w / 2 == pytest.approx(0.5, abs=0.05)


def test_speed_is_limited():
    positions = [0.2] * 10 + [0.8] * 20  # subject teleports without a scene cut
    keyframes, _ = camera_path(samples(positions), [], CROP_9x16)
    kfs = [k.as_dict() for k in keyframes]
    w = CROP_9x16["w"]
    for t in range(0, 29 * 200, 100):
        a, b = crop_at(kfs, t), crop_at(kfs, t + 100)
        assert abs(b["x"] - a["x"]) <= 0.35 * w * 0.1 + 1e-6


def test_scene_cut_jumps_exactly_at_the_cut():
    positions = [0.25] * 15 + [0.75] * 15
    keyframes, _ = camera_path(samples(positions), [3000], CROP_9x16)
    kfs = [k.as_dict() for k in keyframes]
    w = CROP_9x16["w"]
    assert crop_at(kfs, 2999)["x"] + w / 2 == pytest.approx(0.25, abs=0.01)
    assert crop_at(kfs, 3000)["x"] + w / 2 == pytest.approx(0.75, abs=0.01)


def test_no_faces_keeps_the_default_crop():
    keyframes, ratio = camera_path(samples([None] * 10), [], CROP_9x16)
    assert ratio == 0
    assert all(k.x == pytest.approx(CROP_9x16["x"]) for k in keyframes)


def test_gaps_hold_the_last_position():
    keyframes, ratio = camera_path(samples([0.7] * 5 + [None] * 10 + [0.7] * 5), [], CROP_9x16)
    assert ratio == 0.5
    assert len({round(k.x, 4) for k in keyframes}) == 1


def test_long_clips_dont_hit_recursion_limits():
    rng = np.random.default_rng(1)
    positions = list(np.clip(0.5 + np.cumsum(rng.normal(0, 0.01, 2000)), 0.1, 0.9))
    keyframes, _ = camera_path(samples(positions), [], CROP_9x16)
    assert keyframes


def test_piecewise_expression_values():
    expr = piecewise_expr([(0.0, 100), (2.0, 300), (2.0005, 900)])
    assert expr.startswith("trunc(") and "lt(t,0.0000)" in expr
    assert piecewise_expr([(1.0, 42)]) == "42"


# --- end to end ----------------------------------------------------------------------------------


class SquareDetector:
    """Stands in for the face detector: the bright square in the frame is the "face"."""

    def __init__(self, width: int, height: int):
        self.width, self.height = width, height

    def detect(self, frame: np.ndarray) -> list[Face]:
        ys, xs = np.nonzero(frame[:, :, 1] > 200)
        if len(xs) == 0:
            return []
        x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
        return [Face(x=x0 / self.width, y=y0 / self.height, w=(x1 - x0) / self.width, h=(y1 - y0) / self.height, score=1)]


@pytest.fixture
def square_detector(monkeypatch):
    monkeypatch.setattr("app.reframe.service.FaceDetector", SquareDetector)


def _make(path, filters: str, seconds: int = 6):
    subprocess.run(
        [FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", f"color=0x202020:s=1280x720:r=30:d={seconds}",
         "-vf", filters, "-c:v", "libx264", "-preset", "ultrafast", str(path)],
        check=True,
    )  # fmt: skip
    return path


def _square_center_x(video: str, at: float) -> float:
    """Horizontal center of the bright square in a frame of the exported video, 0..1."""
    w, h = (int(v) for v in subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "csv=p=0", video],
        capture_output=True, text=True, check=True).stdout.strip().split(","))  # fmt: skip
    raw = subprocess.run(
        [FFMPEG, "-v", "error", "-ss", f"{at}", "-i", video, "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True, check=True,
    ).stdout
    frame = np.frombuffer(raw, dtype=np.uint8).reshape(h, w)
    cols = np.nonzero((frame > 200).any(axis=0))[0]
    assert len(cols), f"square not visible at {at}s"
    return (cols.min() + cols.max()) / 2 / w


def _export(client, project_id, clip_id, tmp_path, aspect="9:16", **preset):
    preset = {"output_dir": str(tmp_path / "out"), "hardware": False, **preset}
    job = client.post("/exports", json={"clip_ids": [clip_id], "aspects": [aspect], "preset": preset}).json()[0]
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        j = next(x for x in client.get(f"/projects/{project_id}/exports").json() if x["id"] == job["id"])
        if j["status"] in ("done", "failed"):
            assert j["status"] == "done", j["error"]
            return j
        time.sleep(0.2)
    raise AssertionError("export did not finish")


def _import(client, project, path):
    sid = client.post(f"/projects/{project['id']}/sources", json={"path": str(path)}).json()["id"]
    src = wait_for(client, sid, {"ready", "failed"}, timeout=120)
    assert src["status"] == "ready", src["error"]
    return src


@needs_ffmpeg
def test_smart_crop_follows_a_moving_subject(client, project, tmp_path, square_detector):
    # A square drifting left to right at 100 px/s. (overlay, not drawbox: in drawbox `t` means thickness.)
    video = tmp_path / "moving.mp4"
    subprocess.run(
        [FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "color=0x202020:s=1280x720:r=30:d=6",
         "-f", "lavfi", "-i", "color=white:s=100x100:r=30:d=6",
         "-filter_complex", "[0:v][1:v]overlay=x='200+t*100':y=300", "-c:v", "libx264", "-preset", "ultrafast", str(video)],
        check=True,
    )  # fmt: skip
    src = _import(client, project, video)
    clip = client.post(f"/sources/{src['id']}/clips", json={"start_ms": 500, "end_ms": 5500}).json()

    clip = client.put(f"/clips/{clip['id']}/formats/9:16", json={"mode": "smart"}).json()
    fmt = clip["formats"]["9:16"]
    assert fmt["mode"] == "smart" and not fmt["stale"] and fmt["options"]["face_ratio"] == 1.0
    assert fmt["keyframes"][0]["t"] <= 500 and fmt["keyframes"][-1]["t"] >= 5500
    assert fmt["keyframes"][-1]["x"] > fmt["keyframes"][0]["x"]

    job = _export(client, project["id"], clip["id"], tmp_path)
    for at in (0.5, 2.5, 4.5):
        assert _square_center_x(job["output_path"], at) == pytest.approx(0.5, abs=0.15), f"off-center at {at}s"

    # Tracking covers the clip plus a 3 s margin; extending past that marks the framing stale.
    short = client.post(f"/sources/{src['id']}/clips", json={"start_ms": 0, "end_ms": 1000}).json()
    tracked = client.put(f"/clips/{short['id']}/formats/9:16", json={"mode": "smart"}).json()["formats"]["9:16"]
    assert tracked["keyframes"][-1]["t"] == 4000
    assert client.patch(f"/clips/{short['id']}", json={"end_ms": 3900}).json()["formats"]["9:16"]["stale"] is False
    assert client.patch(f"/clips/{short['id']}", json={"end_ms": 5500}).json()["formats"]["9:16"]["stale"] is True


@needs_ffmpeg
def test_smart_crop_jumps_at_a_scene_cut(client, project, tmp_path, square_detector):
    # Left for 3 s, then a hard cut (background brightens) with the square on the right.
    video = _make(
        tmp_path / "cut.mp4",
        "drawbox=x=150:y=300:w=100:h=100:color=white:t=fill:enable='lt(t,3)',"
        "drawbox=x=0:y=0:w=1280:h=720:color=0x707070:t=fill:enable='gte(t,3)',"
        "drawbox=x=1030:y=300:w=100:h=100:color=white:t=fill:enable='gte(t,3)'",
    )
    src = _import(client, project, video)
    clip = client.post(f"/sources/{src['id']}/clips", json={"start_ms": 0, "end_ms": 6000}).json()
    client.put(f"/clips/{clip['id']}/formats/9:16", json={"mode": "smart"})
    job = _export(client, project["id"], clip["id"], tmp_path)
    assert _square_center_x(job["output_path"], 2.5) == pytest.approx(0.5, abs=0.15)
    assert _square_center_x(job["output_path"], 3.2) == pytest.approx(0.5, abs=0.15), "should re-frame right after the cut"


@needs_ffmpeg
def test_export_default_smart_tracks_automatically(client, project, tmp_path, square_detector):
    video = _make(tmp_path / "right.mp4", "drawbox=x=1000:y=300:w=100:h=100:color=white:t=fill", seconds=3)
    src = _import(client, project, video)
    clip = client.post(f"/sources/{src['id']}/clips", json={"start_ms": 0, "end_ms": 3000}).json()
    job = _export(client, project["id"], clip["id"], tmp_path, default_framing="smart")
    assert job["mode"] == "smart"
    assert _square_center_x(job["output_path"], 1.0) == pytest.approx(0.5, abs=0.15)
    fmt = client.get(f"/sources/{src['id']}/clips").json()[0]["formats"]["9:16"]
    assert fmt["keyframes"] and not fmt["stale"]


@needs_ffmpeg
def test_real_face_detector_runs_on_video_without_faces(client, project, tmp_path):
    video = _make(tmp_path / "plain.mp4", "drawbox=x=500:y=300:w=100:h=100:color=white:t=fill", seconds=2)
    src = _import(client, project, video)
    clip = client.post(f"/sources/{src['id']}/clips", json={"start_ms": 0, "end_ms": 2000}).json()
    fmt = client.put(f"/clips/{clip['id']}/formats/9:16", json={"mode": "smart"}).json()["formats"]["9:16"]
    assert fmt["options"]["face_ratio"] == 0
    assert fmt["crop"]["x"] == pytest.approx(default_crop("9:16", 1280, 720)["x"], abs=0.001)
    assert detect.MODEL_PATH.is_file()


@needs_ffmpeg
@pytest.mark.parametrize("background, corner", [("black", (0, 40)), ("white", (215, 256))])
def test_fit_styles(client, project, tmp_path, background, corner):
    video = _make(tmp_path / f"fit_{background}.mp4", "drawbox=x=0:y=0:w=1280:h=720:color=red@1:t=fill", seconds=2)
    src = _import(client, project, video)
    clip = client.post(f"/sources/{src['id']}/clips", json={"start_ms": 0, "end_ms": 1000}).json()
    fit = {"background": background, "dim": 0, "zoom": 1.2, "position": "top"}
    clip = client.put(f"/clips/{clip['id']}/formats/9:16", json={"mode": "fit", "fit": fit}).json()
    assert clip["formats"]["9:16"]["options"] == fit
    job = _export(client, project["id"], clip["id"], tmp_path)

    raw = subprocess.run(
        [FFMPEG, "-v", "error", "-i", job["output_path"], "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True, check=True,
    ).stdout  # fmt: skip
    frame = np.frombuffer(raw, dtype=np.uint8).reshape(1920, 1080)
    lo, hi = corner
    assert lo <= frame[-10, 10] < hi, "bottom corner shows the background colour"
    # The first frame must already contain the picture (it used to be background only).
    assert abs(int(frame[400, 540]) - int(frame[-10, 10])) > 30, "picture missing from the first frame"
    frames = subprocess.run(
        [FFPROBE, "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries", "stream=nb_read_frames",
         "-of", "csv=p=0", job["output_path"]], capture_output=True, text=True, check=True,
    ).stdout.strip()  # fmt: skip
    assert frames == "30"
    # "top" places the picture in the upper part: its band starts well above the middle.
    rows = np.nonzero(np.abs(frame[:, 540].astype(int) - int(frame[-10, 10])) > 30)[0]
    assert rows.min() < 1920 * 0.3
    # zoom 1.2 trims the sides: the picture spans the full width.
    assert abs(int(frame[rows.min() + 20, 2]) - int(frame[-10, 10])) > 30


@needs_ffmpeg
def test_fit_blur_background_is_not_flat(client, project, tmp_path):
    video = _make(tmp_path / "busy.mp4", "drawgrid=w=80:h=80:t=20:c=white", seconds=2)
    src = _import(client, project, video)
    clip = client.post(f"/sources/{src['id']}/clips", json={"start_ms": 0, "end_ms": 1000}).json()
    client.put(f"/clips/{clip['id']}/formats/9:16", json={"mode": "fit", "fit": {"background": "blur", "dim": 0.3}})
    job = _export(client, project["id"], clip["id"], tmp_path)
    raw = subprocess.run(
        [FFMPEG, "-v", "error", "-i", job["output_path"], "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True, check=True,
    ).stdout  # fmt: skip
    frame = np.frombuffer(raw, dtype=np.uint8).reshape(1920, 1080)
    top_band = frame[:300]
    assert top_band.std() > 1, "blurred copy of the picture, not a solid colour"
    assert top_band.max() < 200, "background is blurred and darkened"
