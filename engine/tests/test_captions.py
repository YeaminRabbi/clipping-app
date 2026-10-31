"""Captions: cue building, editing, ASS/SRT output (unit), and transcribe -> edit -> export (end to end)."""

import re
import subprocess
import time
import zipfile
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.captions.ass import build_ass
from app.captions.cues import apply_text_edit, make_cues, to_srt, words_for_clip, wrap
from app.captions.styles import TEMPLATES, resolve
from app.config import Settings
from app.main import create_app
from conftest import BIN_DIR, FFMPEG, FFPROBE, MODELS_DIR, TOKEN, needs_ffmpeg, needs_tts, wait_for


def words(*spec: str, start: int = 0, step: int = 400) -> list[dict]:
    out, t = [], start
    for token in " ".join(spec).split():
        if token == "|":  # a pause
            t += 1000
            continue
        out.append({"start": t, "end": t + 300, "text": token})
        t += step
    return out


# --- unit ----------------------------------------------------------------------------------------


def test_cues_respect_word_limits_sentences_and_pauses():
    style = resolve("bold_pop")  # 3 words per cue
    cues = make_cues(words("one two three four five. six | seven"), style)
    assert [c.text for c in cues] == ["one two three", "four five.", "six", "seven"]
    for a, b in zip(cues, cues[1:]):
        assert a.end <= b.start, "cues never overlap"
        assert a.end >= a.words[-1]["end"], "a cue stays up until its last word ends"


def test_cues_respect_character_limit():
    style = resolve("minimal")  # 26 chars, 1 line
    cues = make_cues(words("internationalization documentation considerations everywhere"), style)
    assert all(len(c.text) <= 26 or len(c.words) == 1 for c in cues)


def test_words_for_clip_clamps_to_edges():
    clip = words_for_clip(words("a b c d e"), 500, 1500)
    assert [w["text"] for w in clip] == ["b", "c", "d"]
    assert clip[0]["start"] >= 500 and clip[-1]["end"] <= 1500


def test_text_edits_keep_timing():
    w = words("helo wrld again")
    fixed = apply_text_edit(w, [0, 1], "hello world")
    assert [x["text"] for x in fixed] == ["hello", "world", "again"]
    assert fixed[0]["start"] == w[0]["start"] and fixed[1]["end"] == w[1]["end"]

    longer = apply_text_edit(w, [0, 1], "hello there big world")
    assert [x["text"] for x in longer[:4]] == ["hello", "there", "big", "world"]
    assert longer[0]["start"] == w[0]["start"] and longer[3]["end"] == w[1]["end"]
    assert all(a["end"] <= b["start"] + 1 for a, b in zip(longer, longer[1:4]))

    assert [x["text"] for x in apply_text_edit(w, [1], "")] == ["helo", "again"]


def test_wrap_balances_two_lines():
    assert wrap("short", 20, 2) == "short"
    assert wrap("the quick brown fox jumps over", 16, 2) == "the quick brown\nfox jumps over"


def test_srt_times_are_relative_to_the_clip():
    style = resolve("classic")
    cues = make_cues(words("hello there.", start=10_000), style)
    srt = to_srt(cues, style, offset_ms=10_000)
    # Two words (0-300, 400-700 ms after the offset) plus the 300 ms hold.
    assert srt.startswith("1\n00:00:00,000 --> 00:00:01,000\n")
    assert "hello there." in srt


def test_ass_karaoke_pop_and_escaping():
    w = words("make {money} fast")
    pop = build_ass(make_cues(w, resolve("bold_pop")), resolve("bold_pop"), 1080, 1920, 0)
    assert pop.count("Dialogue:") == 3, "one event per spoken word"
    assert "MAKE" in pop and "{money}" not in pop and "MONEY" in pop, "uppercase, braces removed"
    assert "\\c&H0000E6FF" in pop, "spoken word in the yellow highlight (#FFE600 as ASS &HAABBGGRR)"

    kar = build_ass(make_cues(w, resolve("karaoke")), resolve("karaoke"), 1080, 1920, 0)
    assert kar.count("Dialogue:") == 1 and kar.count("\\kf") == 3

    classic = build_ass(make_cues(w, resolve("classic")), resolve("classic"), 1920, 1080, 0)
    assert ",3," in classic.split("Style: Caption,")[1], "classic uses an opaque box (BorderStyle 3)"
    assert "PlayResX: 1920" in classic and "PlayResY: 1080" in classic


def test_style_overrides_are_validated():
    style = resolve("bold_pop", {"size": 999, "font": "Comic Sans", "position": "sideways", "color": "#FF0000", "bogus": 1})
    assert style.size == 200 and style.font == TEMPLATES["bold_pop"].font
    assert style.position == TEMPLATES["bold_pop"].position and style.color == "#FF0000"


# --- end to end ----------------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", token=TOKEN, bin_dir=BIN_DIR, models_dir=MODELS_DIR)
    settings.projects_dir.mkdir(parents=True)
    with TestClient(create_app(settings), headers={"x-engine-token": TOKEN}) as c:
        yield c


@pytest.fixture
def clip(client, podcast) -> dict:
    pid = client.post("/projects", json={"name": "Show"}).json()["id"]
    sid = client.post(f"/projects/{pid}/sources", json={"path": str(podcast)}).json()["id"]
    assert wait_for(client, sid, {"ready", "failed"}, timeout=120)["status"] == "ready"
    # "Here is the most important lesson about pricing. Never compete on price alone." (~12-19 s)
    return client.post(f"/sources/{sid}/clips", json={"start_ms": 11_500, "end_ms": 20_000}).json() | {"project_id": pid}


def _wait_analysis(client, source_id):
    for _ in range(600):
        a = client.get(f"/sources/{source_id}/analysis").json()
        if a and a["status"] in ("done", "failed"):
            return a
        time.sleep(0.2)
    raise AssertionError("transcription did not finish")


def _export(client, project_id, clip_id, out, **preset):
    preset = {"output_dir": str(out), "hardware": False, "default_framing": "center", **preset}
    jobs = client.post("/exports", json={"clip_ids": [clip_id], "aspects": preset.pop("aspects", ["9:16"]), "preset": preset}).json()
    ids = {j["id"] for j in jobs}
    for _ in range(600):
        done = [j for j in client.get(f"/projects/{project_id}/exports").json() if j["id"] in ids]
        if all(j["status"] in ("done", "failed") for j in done):
            assert all(j["status"] == "done" for j in done), [j["error"] for j in done]
            return done
        time.sleep(0.2)
    raise AssertionError("export did not finish")


def _frame(path: str, at: float) -> np.ndarray:
    raw = subprocess.run(
        [FFMPEG, "-v", "error", "-ss", f"{at}", "-i", path, "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True, check=True,
    ).stdout  # fmt: skip
    return np.frombuffer(raw, dtype=np.uint8).reshape(1920, 1080)


@needs_ffmpeg
@needs_tts
def test_transcribe_edit_and_reset(client, clip):
    assert client.get(f"/clips/{clip['id']}/captions").json()["status"] == "needs_transcript"
    res = client.post(f"/sources/{clip['source_id']}/transcribe", json={"model": "tiny"})
    assert res.status_code == 202 and res.json()["task"] == "transcribe"
    assert _wait_analysis(client, clip["source_id"])["status"] == "done"

    caps = client.get(f"/clips/{clip['id']}/captions").json()
    assert caps["status"] == "ready" and not caps["edited"]
    text = " ".join(c["text"] for c in caps["cues"]).lower()
    assert "pricing" in text and "never compete" in text
    assert all(c["start"] >= clip["start_ms"] and c["end"] <= clip["end_ms"] for c in caps["cues"])

    first = caps["cues"][0]
    edited = client.post(
        f"/clips/{clip['id']}/captions/edit", json={"indices": [w["index"] for w in first["words"]], "text": "HELLO THERE"}
    ).json()
    assert edited["edited"] and edited["cues"][0]["text"].startswith("HELLO")
    assert client.get(f"/sources/{clip['source_id']}/clips").json()[0]["status"] == "kept"

    reset = client.delete(f"/clips/{clip['id']}/captions").json()
    assert not reset["edited"] and reset["cues"][0]["text"] == first["text"]


@needs_ffmpeg
@needs_tts
def test_style_endpoints(client, clip):
    templates = client.get("/caption-templates").json()
    assert set(templates["templates"]) == {"bold_pop", "karaoke", "classic", "minimal"}
    assert "Arial Black" in templates["fonts"]
    pid = clip["project_id"]
    assert client.get(f"/projects/{pid}/caption-style").json()["template"] == "bold_pop"
    saved = client.put(f"/projects/{pid}/caption-style", json={"template": "classic", "overrides": {"color": "#00FF00"}}).json()
    assert saved["template"] == "classic" and saved["style"]["color"] == "#00FF00" and saved["style"]["box"]


@needs_ffmpeg
@needs_tts
def test_export_burns_captions_writes_srt_and_zips(client, clip, tmp_path, monkeypatch):
    # Not transcribed yet: the export transcribes by itself (with the small model, for test speed).
    monkeypatch.setattr("app.analysis.transcribe.DEFAULT_MODEL", "tiny")
    out = tmp_path / "out"
    jobs = _export(client, clip["project_id"], clip["id"], out, captions="burn_srt", zip=True, aspects=["9:16", "1:1"])
    portrait = next(j for j in jobs if j["aspect"] == "9:16")
    assert portrait["burn_captions"] and portrait["export_srt"]

    srt = Path(portrait["srt_path"]).read_text(encoding="utf-8")
    first_time = re.search(r"(\d\d):(\d\d):(\d\d),(\d{3}) -->", srt)
    assert first_time and first_time.group(1, 2) == ("00", "00") and int(first_time.group(3)) < 3
    assert "PRICING" in srt.upper()

    plain = _export(client, clip["project_id"], clip["id"], tmp_path / "plain", captions="off")[0]
    # Captions sit in the middle (bold_pop): that band must differ between the two renders.
    diffs = [np.abs(_frame(portrait["output_path"], t).astype(int) - _frame(plain["output_path"], t)).mean() for t in (1.0, 3.0, 5.0)]
    assert max(diffs) > 2, f"burned-in captions not visible (mean diffs {diffs})"
    frames = subprocess.run(
        [FFPROBE, "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries", "stream=nb_read_frames",
         "-of", "csv=p=0", portrait["output_path"]], capture_output=True, text=True, check=True,
    ).stdout.strip()  # fmt: skip
    assert frames == str(round(8.5 * 30)), "captions must not change the exact frame count"

    batches = client.get(f"/projects/{clip['project_id']}/export-batches").json()
    assert batches and batches[0]["zip_path"], batches
    with zipfile.ZipFile(batches[0]["zip_path"]) as zf:
        names = sorted(zf.namelist())
    assert sum(n.endswith(".mp4") for n in names) == 2 and sum(n.endswith(".srt") for n in names) == 2
