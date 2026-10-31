"""Active-speaker framing: tracking and switching rules (unit), and a full track + export (end to end)."""

import subprocess
import time

import numpy as np
import pytest

from app.reframe.detect import Face
from app.reframe.speaker import MIN_SHOT_MS, SWITCH_CONFIRM_MS, assign_tracks, pick_speaker
from conftest import FFMPEG, FFPROBE, needs_ffmpeg, wait_for

LEFT, RIGHT = 0.25, 0.75


def face(cx: float, size: float = 0.15) -> Face:
    return Face(x=cx - size / 2, y=0.3, w=size, h=size, score=0.9, mouth_x=cx, mouth_y=0.3 + size * 0.78, mouth_w=size * 0.4)


def two_people(seconds: float, step: int = 100) -> list[tuple[int, list[Face]]]:
    return [(i * step, [face(LEFT), face(RIGHT)]) for i in range(int(seconds * 1000 / step))]


def talking(tracked, who: dict[int, tuple[int, int]]) -> dict[tuple[int, int], float]:
    """Mouth activity: each track id moves its mouth during its (start, end) window."""
    act = {}
    for t, faces in tracked:
        for tid in faces:
            lo, hi = who.get(tid, (0, 0))
            act[(t, tid)] = 8.0 if lo <= t < hi else 0.5
    return act


def framed_x(result, t: int) -> float:
    return next(f.cx for st, f in result.subject if st >= t)


# --- unit ----------------------------------------------------------------------------------------


def test_tracks_keep_their_ids_as_people_move():
    samples = [(i * 100, [face(LEFT + i * 0.002), face(RIGHT - i * 0.002)]) for i in range(30)]
    tracked = assign_tracks(samples)
    left_ids = {tid for _, faces in tracked for tid, f in faces.items() if f.cx < 0.5}
    right_ids = {tid for _, faces in tracked for tid, f in faces.items() if f.cx >= 0.5}
    assert len(left_ids) == 1 and len(right_ids) == 1 and left_ids != right_ids, "each person keeps one id"


def test_camera_follows_whoever_talks_and_cuts_when_they_start():
    tracked = assign_tracks(two_people(10))
    left_id = next(tid for tid, f in tracked[0][1].items() if f.cx < 0.5)
    right_id = 1 - left_id
    act = talking(tracked, {left_id: (0, 4000), right_id: (4000, 10_000)})
    result = pick_speaker(tracked, act, [True] * len(tracked))
    assert result.speakers == 2 and len(result.switches) == 1
    assert framed_x(result, 2000) == pytest.approx(LEFT)
    assert framed_x(result, 8000) == pytest.approx(RIGHT)
    # The cut lands around when the right person started talking (activity is averaged over ~0.8 s),
    # not after the confirmation delay.
    assert 3500 <= result.switches[0] <= 4300


def test_brief_interjections_dont_cause_a_cut():
    tracked = assign_tracks(two_people(8))
    left_id = next(tid for tid, f in tracked[0][1].items() if f.cx < 0.5)
    right_id = 1 - left_id
    # Right says "yeah" for 300 ms in the middle of left's turn.
    act = talking(tracked, {left_id: (0, 8000), right_id: (3000, 3300)})
    result = pick_speaker(tracked, act, [True] * len(tracked))
    assert result.switches == []


def test_no_switching_during_silence():
    tracked = assign_tracks(two_people(8))
    left_id = next(tid for tid, f in tracked[0][1].items() if f.cx < 0.5)
    right_id = 1 - left_id
    # Right's mouth moves (chewing, smiling) but there's no sound.
    act = talking(tracked, {left_id: (0, 1000), right_id: (2000, 8000)})
    speech = [t < 1000 for t, _ in tracked]
    result = pick_speaker(tracked, act, speech)
    assert result.switches == [] and framed_x(result, 6000) == pytest.approx(LEFT)


def test_shots_last_a_minimum_time():
    tracked = assign_tracks(two_people(10))
    left_id = next(tid for tid, f in tracked[0][1].items() if f.cx < 0.5)
    right_id = 1 - left_id
    # Rapid back-and-forth every second.
    act = {(t, tid): (8.0 if (t // 1000) % 2 == (0 if tid == left_id else 1) else 0.5) for t, faces in tracked for tid in faces}
    result = pick_speaker(tracked, act, [True] * len(tracked))
    gaps = [b - a for a, b in zip([0] + result.switches, result.switches)]
    assert all(g >= MIN_SHOT_MS - SWITCH_CONFIRM_MS for g in gaps), gaps


def test_passers_by_never_get_the_camera():
    samples = two_people(10)
    # A third face appears briefly on the right edge, talking a lot.
    samples = [(t, faces + ([face(0.95, 0.08)] if 3000 <= t < 4000 else [])) for t, faces in samples]
    tracked = assign_tracks(samples)
    extra = next(tid for _, faces in tracked for tid, f in faces.items() if f.cx > 0.9)
    act = talking(tracked, {extra: (0, 10_000)})
    result = pick_speaker(tracked, act, [True] * len(tracked))
    assert all(f is None or f.cx < 0.9 for _, f in result.subject)


# --- end to end ----------------------------------------------------------------------------------


class TwoPersonDetector:
    """Stands in for the face detector: a bright square in each half of the frame is a "face", with its
    mouth at the bottom of the square."""

    def __init__(self, width: int, height: int):
        self.width, self.height = width, height

    def detect(self, frame: np.ndarray) -> list[Face]:
        faces = []
        half = self.width // 2
        for x_off in (0, half):
            ys, xs = np.nonzero(frame[:, x_off : x_off + half, 1] > 150)
            if len(xs) < 50:
                continue
            x0, x1, y0, y1 = xs.min() + x_off, xs.max() + x_off, ys.min(), ys.max()
            w, h = (x1 - x0) / self.width, (y1 - y0) / self.height
            faces.append(Face(x=x0 / self.width, y=y0 / self.height, w=w, h=h, score=1,
                              mouth_x=(x0 + x1) / 2 / self.width, mouth_y=(y0 + (y1 - y0) * 0.8) / self.height,
                              mouth_w=w * 0.4))  # fmt: skip
        return faces


@needs_ffmpeg
def test_export_cuts_between_two_talking_people(client, project, tmp_path, monkeypatch):
    monkeypatch.setattr("app.reframe.service.FaceDetector", TwoPersonDetector)
    # Two "people"; each one's mouth flickers (talks) in turn: left for 0-4 s, right for 4-8 s. Constant tone = speech.
    video = tmp_path / "two.mp4"
    mouth = "drawbox=x={x}:y=430:w=90:h=40:color=black:t=fill:enable='between(t,{a},{b})*lt(mod(t,0.2),0.1)'"
    filters = ",".join([
        "drawbox=x=150:y=250:w=220:h=220:color=white:t=fill",
        "drawbox=x=910:y=250:w=220:h=220:color=white:t=fill",
        mouth.format(x=215, a=0, b=4), mouth.format(x=975, a=4, b=8),
    ])  # fmt: skip
    subprocess.run(
        [FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "color=0x303030:s=1280x720:r=30:d=8",
         "-f", "lavfi", "-i", "sine=frequency=300:duration=8", "-vf", filters,
         "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(video)],
        check=True,
    )  # fmt: skip
    sid = client.post(f"/projects/{project['id']}/sources", json={"path": str(video)}).json()["id"]
    assert wait_for(client, sid, {"ready", "failed"}, timeout=120)["status"] == "ready"
    clip = client.post(f"/sources/{sid}/clips", json={"start_ms": 0, "end_ms": 8000}).json()

    fmt = client.put(f"/clips/{clip['id']}/formats/9:16", json={"mode": "smart", "follow": "speaker"}).json()["formats"]["9:16"]
    assert fmt["options"]["followed"] == "speaker" and fmt["options"]["speakers"] == 2
    assert fmt["options"]["switches"] == 1

    job = client.post("/exports", json={"clip_ids": [clip["id"]], "aspects": ["9:16"],
                                        "preset": {"output_dir": str(tmp_path / "out"), "hardware": False}}).json()[0]  # fmt: skip
    for _ in range(600):
        job = next(j for j in client.get(f"/projects/{project['id']}/exports").json() if j["id"] == job["id"])
        if job["status"] in ("done", "failed"):
            break
        time.sleep(0.2)
    assert job["status"] == "done", job["error"]

    def bright_center(at: float) -> float:
        raw = subprocess.run(
            [FFMPEG, "-v", "error", "-ss", f"{at}", "-i", job["output_path"], "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
            capture_output=True, check=True,
        ).stdout  # fmt: skip
        frame = np.frombuffer(raw, dtype=np.uint8).reshape(1920, 1080)
        cols = np.nonzero((frame > 200).sum(axis=0) > 100)[0]
        return (cols.min() + cols.max()) / 2 / 1080

    # Each speaker is centered while they talk; the other person is out of frame.
    assert bright_center(2.0) == pytest.approx(0.5, abs=0.12)
    assert bright_center(6.5) == pytest.approx(0.5, abs=0.12)
    probe = subprocess.run(
        [FFPROBE, "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries", "stream=nb_read_frames",
         "-of", "csv=p=0", job["output_path"]], capture_output=True, text=True, check=True,
    ).stdout.strip()  # fmt: skip
    assert probe == "240"


@needs_ffmpeg
def test_largest_mode_ignores_who_is_talking(client, project, tmp_path, monkeypatch):
    monkeypatch.setattr("app.reframe.service.FaceDetector", TwoPersonDetector)
    video = tmp_path / "two_still.mp4"
    subprocess.run(
        [FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "color=0x303030:s=1280x720:r=30:d=3",
         "-vf", "drawbox=x=150:y=250:w=260:h=260:color=white:t=fill,drawbox=x=910:y=250:w=180:h=180:color=white:t=fill",
         "-c:v", "libx264", "-preset", "ultrafast", str(video)],
        check=True,
    )  # fmt: skip
    sid = client.post(f"/projects/{project['id']}/sources", json={"path": str(video)}).json()["id"]
    wait_for(client, sid, {"ready"}, timeout=120)
    clip = client.post(f"/sources/{sid}/clips", json={"start_ms": 0, "end_ms": 3000}).json()
    fmt = client.put(f"/clips/{clip['id']}/formats/9:16", json={"mode": "smart", "follow": "largest"}).json()["formats"]["9:16"]
    assert fmt["options"]["follow"] == "largest" and fmt["options"]["followed"] == "largest"
    assert fmt["keyframes"][0]["x"] + fmt["keyframes"][0]["w"] / 2 < 0.5, "frames the bigger (left) face"
