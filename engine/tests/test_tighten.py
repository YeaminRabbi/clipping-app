"""Tighten: cutting filler words and long pauses (unit), and exporting a tightened clip (end to end)."""

import json
import re
import subprocess
import time
from pathlib import Path

import numpy as np
import pytest

from app.analysis.transcribe import TRANSCRIPT_VERSION
from app.edit.cutplan import TightenSettings, is_filler, plan_cuts
from app.edit.timemap import TimeMap
from app.reframe.track import crop_at
from conftest import FFMPEG, FFPROBE, needs_ffmpeg, wait_for

FPS = 30.0


def quiet_between(*loud: tuple[int, int]):
    """quiet_share() where only the given ranges have sound."""

    def share(a, b, ignore):
        step, counted, quiet, t = 10, 0, 0, a
        while t < b:
            if not any(lo <= t < hi for lo, hi in ignore):
                counted += 1
                quiet += not any(lo <= t < hi for lo, hi in loud)
            t += step
        return quiet / counted if counted else 1.0

    return share


def w(text, start, end):
    return {"text": text, "start": start, "end": end}


WORDS = [w("Pricing", 0, 400), w("matters.", 420, 900), w("Um,", 1200, 1450), w("customers", 1500, 2000),
         w("pay", 3500, 3700), w("for", 3720, 3900), w("value.", 3920, 4400)]  # fmt: skip
SPEECH = [(x["start"], x["end"]) for x in WORDS]


# --- unit ----------------------------------------------------------------------------------------


def test_filler_detection():
    assert all(is_filler(t) for t in ["um", "Um,", "uh...", "UHM", "hmm"])
    assert not any(is_filler(t) for t in ["umbrella", "huh?", "like", "so"])


def test_plan_removes_fillers_and_long_quiet_pauses():
    plan = plan_cuts(WORDS, 0, 4400, quiet_between(*SPEECH), TightenSettings(max_pause_ms=500), FPS)
    assert plan.fillers == 1 and plan.pauses == 1
    reasons = {c.reason for c in plan.cuts}
    assert reasons == {"filler", "pause"}
    # The 1.5 s pause between "customers" and "pay" is shortened to 0.5 s.
    pause = next(c for c in plan.cuts if c.reason == "pause")
    assert pause.end - pause.start == pytest.approx(1000, abs=2 * 1000 / FPS)
    # Every cut and segment edge is on a frame boundary, and no kept word is touched.
    for a, b in plan.segments:
        assert (a * FPS / 1000) == pytest.approx(round(a * FPS / 1000), abs=1e-6)
        assert (b * FPS / 1000) == pytest.approx(round(b * FPS / 1000), abs=1e-6)
    for word in WORDS:
        if is_filler(word["text"]):
            continue
        for c in plan.cuts:
            assert word["end"] <= c.start or word["start"] >= c.end, f"cut {c} touches {word['text']}"
    assert plan.duration_ms == pytest.approx(4400 - sum(c.end - c.start for c in plan.cuts), abs=1)


def test_filler_with_no_duration_is_still_removed_and_counted_honestly():
    # Whisper reported "uh," at exactly 11360-11360 in a real run: the old code dropped its (80 ms) cut
    # but still counted it as removed.
    words = [w("honestly,", 10640, 10720), w("uh,", 11360, 11360), w("it", 11480, 11720), w("worked", 11720, 12000)]
    plan = plan_cuts(words, 10640, 12000, quiet_between(*[(x["start"], x["end"]) for x in words]), TightenSettings(remove_pauses=False), FPS)
    assert plan.fillers == 1 and len(plan.cuts) == 1
    cut = plan.cuts[0]
    assert cut.start >= 10740 and cut.end <= 11460 and cut.start <= 11360 <= cut.end, "cuts the gap the filler sits in"
    assert all(word["end"] <= cut.start or word["start"] >= cut.end for word in words if word["text"] != "uh,")
    # With no room at all, nothing is cut and nothing is claimed.
    tight = [w("so", 0, 300), w("uh,", 330, 330), w("yes", 345, 700)]
    plan = plan_cuts(tight, 0, 700, quiet_between(), TightenSettings(remove_pauses=False), FPS)
    assert plan.fillers == 0 and plan.cuts == []


def test_loud_gaps_are_kept():
    # Laughter fills the 1.5 s gap: it isn't a pause.
    plan = plan_cuts(WORDS, 0, 4400, quiet_between(*SPEECH, (2000, 3500)), TightenSettings(remove_fillers=False), FPS)
    assert plan.pauses == 0 and plan.cuts == []


def test_settings_switch_each_kind_off():
    only_pauses = plan_cuts(WORDS, 0, 4400, quiet_between(*SPEECH), TightenSettings(remove_fillers=False), FPS)
    assert {c.reason for c in only_pauses.cuts} == {"pause"}
    only_fillers = plan_cuts(WORDS, 0, 4400, quiet_between(*SPEECH), TightenSettings(remove_pauses=False), FPS)
    assert {c.reason for c in only_fillers.cuts} == {"filler"}
    assert TightenSettings.from_dict({"remove_fillers": False, "remove_pauses": False}) is None
    assert TightenSettings.from_dict({"remove_pauses": True, "max_pause_ms": 99999}).max_pause_ms == 3000


def test_short_gaps_and_tiny_cuts_are_left_alone():
    words = [w("one", 0, 300), w("two", 600, 900), w("three", 1000, 1300)]
    plan = plan_cuts(words, 0, 1300, quiet_between(), TightenSettings(max_pause_ms=400), FPS)
    assert plan.cuts == [] and plan.segments == [(0.0, 1300.0)]


def test_timemap_retimes_words_and_crop_path():
    tm = TimeMap([(0.0, 1000.0), (2000.0, 3000.0)])
    assert tm.duration == 2000
    assert tm.to_output(500) == 500 and tm.to_output(1500) is None and tm.to_output(2500) == 1500
    words = tm.map_words([w("a", 100, 400), w("um", 1200, 1400), w("b", 2100, 2400)])
    assert [x["text"] for x in words] == ["a", "b"] and words[1]["start"] == 1100
    path = [{"t": 0, "x": 0.0, "y": 0, "w": 0.3, "h": 1}, {"t": 3000, "x": 0.6, "y": 0, "w": 0.3, "h": 1}]
    mapped = tm.map_keyframes(path, crop_at)
    # Second segment starts where the source path is at 2 s (x = 0.4), at output time 1 s: a jump at the join.
    second = next(k for k in mapped if k["t"] == 1000)
    assert second["x"] == pytest.approx(0.4)
    # ... while the first segment ends where the path is at 1 s (x = 0.2).
    before = [k for k in mapped if k["t"] < 1000][-1]
    assert before["x"] == pytest.approx(0.2, abs=0.01)


# --- end to end ----------------------------------------------------------------------------------

# Speech at 0.2-1.8 s ("hello"), a filler at 4.0-4.6 s ("um"), speech at 4.7-5.9 s ("world").
# The picture is blue, except red during the silent pause (2-4 s) and green during the filler.
TONE = "aevalsrc='0.5*sin(2*PI*440*t)*(between(t,0.2,1.8)+between(t,4.0,4.6)+between(t,4.7,5.9))':s=48000:d=6"
COLORS = ("drawbox=x=0:y=0:w=iw:h=ih:color=red:t=fill:enable='between(t,2,3.999)',"
          "drawbox=x=0:y=0:w=iw:h=ih:color=0x00FF00:t=fill:enable='between(t,4,4.599)'")  # fmt: skip
TRANSCRIPT = [w("Hello", 200, 1800), w("um", 4000, 4600), w("world.", 4700, 5900)]


@pytest.fixture
def tight_source(client, project, tmp_path):
    video = tmp_path / "talk.mp4"
    subprocess.run(
        [FFMPEG, "-y", "-v", "error", "-f", "lavfi", "-i", "color=blue:s=640x360:r=30:d=6", "-f", "lavfi", "-i", TONE,
         "-vf", COLORS, "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(video)],
        check=True,
    )  # fmt: skip
    sid = client.post(f"/projects/{project['id']}/sources", json={"path": str(video)}).json()["id"]
    src = wait_for(client, sid, {"ready", "failed"}, timeout=120)
    assert src["status"] == "ready", src["error"]
    # A known transcript, so the test doesn't depend on speech recognition.
    work = Path(client.app.state.ingest.source_dir(project["id"], sid))
    (work / "transcript.json").write_text(json.dumps({"version": TRANSCRIPT_VERSION, "model": "small", "language": "en", "words": TRANSCRIPT}))
    return src


def _export(client, project_id, clip_id, out, **preset):
    preset = {"output_dir": str(out), "hardware": False, "default_framing": "center", **preset}
    job = client.post("/exports", json={"clip_ids": [clip_id], "aspects": [preset.pop("aspect", "16:9")], "preset": preset}).json()[0]
    for _ in range(600):
        job = next(j for j in client.get(f"/projects/{project_id}/exports").json() if j["id"] == job["id"])
        if job["status"] in ("done", "failed"):
            assert job["status"] == "done", job["error"]
            return job
        time.sleep(0.2)
    raise AssertionError("export did not finish")


def _frame_colors(path: str) -> list[str]:
    raw = subprocess.run(
        [FFMPEG, "-v", "error", "-i", path, "-vf", "scale=4:4", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, check=True,
    ).stdout  # fmt: skip
    frames = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 16, 3).mean(axis=1)
    return ["red" if r > 150 and g < 100 else "green" if g > 150 and r < 100 else "blue" if b > 150 else "?" for r, g, b in frames]


def _durations(path: str) -> dict[str, float]:
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-show_entries", "stream=codec_type,duration", "-of", "json", path],
        capture_output=True, text=True, check=True,
    ).stdout
    return {s["codec_type"]: float(s["duration"]) for s in json.loads(out)["streams"]}


@needs_ffmpeg
def test_tightened_export_drops_filler_and_pause(client, project, tight_source, tmp_path):
    clip = client.post(f"/sources/{tight_source['id']}/clips", json={"start_ms": 0, "end_ms": 6000}).json()
    assert client.get(f"/clips/{clip['id']}/cut-plan").json() == {"status": "off"}

    clip = client.patch(f"/clips/{clip['id']}", json={"tighten": {"remove_fillers": True, "remove_pauses": True, "max_pause_ms": 500}}).json()
    assert clip["tighten"]["max_pause_ms"] == 500
    plan = client.get(f"/clips/{clip['id']}/cut-plan").json()
    assert plan["status"] == "ready" and plan["fillers"] == 1 and plan["pauses"] >= 1
    assert plan["removed_ms"] > 2000

    job = _export(client, project["id"], clip["id"], tmp_path / "out", captions="srt")
    colors = _frame_colors(job["output_path"])
    expected_frames = round(plan["duration_ms"] * 30 / 1000)
    assert len(colors) == expected_frames, "exact frame count for the joined segments"
    assert colors.count("green") == 0, "the filler is gone"
    assert colors.count("red") <= 3, "the long pause is gone (at most a frame or two of its edge)"
    d = _durations(job["output_path"])
    assert d["audio"] == pytest.approx(d["video"], abs=0.05), "sound stays in sync with the picture"

    srt = Path(job["srt_path"]).read_text(encoding="utf-8")
    words = srt.lower().split()
    assert "um" not in words and "hello" in words and "world." in words
    last_end = re.findall(r"--> (\d\d):(\d\d):(\d\d),(\d{3})", srt)[-1]
    assert int(last_end[2]) + int(last_end[3]) / 1000 <= plan["duration_ms"] / 1000 + 0.01

    # Captions in the editor leave out the cut filler too.
    cues = client.get(f"/clips/{clip['id']}/captions").json()["cues"]
    assert all(word["text"] != "um" for cue in cues for word in cue["words"])

    # Turning it off restores the full clip.
    assert client.patch(f"/clips/{clip['id']}", json={"tighten": None}).json()["tighten"] is None
    assert client.get(f"/clips/{clip['id']}/cut-plan").json() == {"status": "off"}


@needs_ffmpeg
def test_tighten_all_on_export_and_smart_framing(client, project, tight_source, tmp_path):
    clip = client.post(f"/sources/{tight_source['id']}/clips", json={"start_ms": 0, "end_ms": 6000}).json()
    job = _export(client, project["id"], clip["id"], tmp_path / "out", tighten_all=True, default_framing="smart", aspect="9:16")
    colors = _frame_colors(job["output_path"])
    assert colors.count("green") == 0 and len(colors) < 150, "clips without their own setting are tightened too"
    assert job["mode"] == "smart"
