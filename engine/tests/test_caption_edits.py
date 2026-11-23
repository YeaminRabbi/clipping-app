"""Editing captions through the API, on a source with a known transcript (no FFmpeg or speech needed)."""

import json

import numpy as np
import pytest

from app.captions.cues import apply_text_edit


def w(text: str, start: int, end: int) -> dict:
    return {"start": start, "end": end, "text": text}


WORDS = [
    w("Um,", 500, 900), w("hello", 1000, 1300), w("there", 1350, 1700), w("friend.", 1750, 2200),
    w("Second", 4000, 4300), w("uh", 4320, 4700), w("line.", 4750, 5200),
    w("Last", 8000, 8300), w("words.", 8350, 8800),
]  # fmt: skip


@pytest.fixture
def clip(client, project) -> dict:
    with client.app.state.db.connect() as conn:
        sid = conn.execute(
            """INSERT INTO sources (project_id, origin, path, status, duration_ms, fps, width, height, has_audio, proxy_path)
               VALUES (?, 'file', 'x.mp4', 'ready', 20000, 30, 1920, 1080, 1, 'p.mp4')""",
            (project["id"],),
        ).lastrowid
    work = client.app.state.ingest.source_dir(project["id"], sid)
    work.mkdir(parents=True)
    (work / "transcript.json").write_text(json.dumps({"version": 2, "model": "base", "language": "en", "words": WORDS}))
    np.save(work / "loudness.npy", np.full(200, -20.0))
    client.put(f"/projects/{project['id']}/caption-style", json={"template": "minimal"})
    return client.post(f"/sources/{sid}/clips", json={"start_ms": 0, "end_ms": 10000}).json()


def cues(client, clip) -> list[dict]:
    return client.get(f"/clips/{clip['id']}/captions").json()["cues"]


def texts(client, clip) -> list[str]:
    return [c["text"] for c in cues(client, clip)]


def edit(client, clip, cue: dict, text: str):
    res = client.post(f"/clips/{clip['id']}/captions/edit", json={"indices": [x["index"] for x in cue["words"]], "text": text})
    assert res.status_code == 200, res.text
    return res.json()


def tighten(client, clip, on: bool = True):
    value = {"remove_fillers": True, "remove_pauses": False} if on else None
    client.patch(f"/clips/{clip['id']}", json={"tighten": value})


# --- editing a tightened clip (F-03) -------------------------------------------------------------


def test_editing_a_tightened_clip_changes_the_words_that_were_shown(client, clip):
    tighten(client, clip)
    assert texts(client, clip) == ["hello there friend.", "Second line.", "Last words."]
    edit(client, clip, cues(client, clip)[0], "HELLO there friend.")
    assert texts(client, clip) == ["HELLO there friend.", "Second line.", "Last words."]
    # A cue with a hidden filler in the middle.
    edit(client, clip, cues(client, clip)[1], "Second LINE.")
    assert texts(client, clip) == ["HELLO there friend.", "Second LINE.", "Last words."]
    # The fillers are still there when Tighten is turned off.
    tighten(client, clip, on=False)
    assert texts(client, clip) == ["Um, HELLO there friend.", "Second uh LINE.", "Last words."]


def test_a_longer_text_never_lands_in_the_removed_part(client, clip):
    tighten(client, clip)
    edit(client, clip, cues(client, clip)[1], "Second all new big line.")
    assert texts(client, clip) == ["hello there friend.", "Second all new big line.", "Last words."]


def test_edit_rejects_indices_out_of_order_or_range(client, clip):
    url = f"/clips/{clip['id']}/captions/edit"
    for bad in ([2, 1], [1, 1], [-1, 0], [0, 99]):
        assert client.post(url, json={"indices": bad, "text": "x"}).status_code == 422, bad


def test_new_words_are_timed_around_hidden_ones():
    words = [w("a", 0, 300), w("um", 300, 900), w("b", 900, 1200), w("c", 1300, 1400)]
    out = apply_text_edit(words, [0, 2], "aa bb cc")
    assert [x["text"] for x in out] == ["aa", "bb", "um", "cc", "c"] or [x["text"] for x in out] == ["aa", "um", "bb", "cc", "c"]
    for x in out:
        if x["text"] != "um":
            assert not 300 < (x["start"] + x["end"]) / 2 < 900, x


# --- caption style values (F-20) -----------------------------------------------------------------

BAD = [
    {"size": "big"}, {"size": 5}, {"size": 100000}, {"color": "red"}, {"color": "#FFF"}, {"color": 5}, {"highlight": "#12345G"},
    {"color": "#FFFFFF\nDialogue: x"}, {"position": "left"}, {"font": "Comic Sans"}, {"uppercase": "maybe"}, {"size": None, "color": []},
]  # fmt: skip


@pytest.mark.parametrize("overrides", BAD)
def test_bad_style_values_are_rejected_and_not_saved(client, project, overrides):
    url = f"/projects/{project['id']}/caption-style"
    client.put(url, json={"template": "classic", "overrides": {"size": 60}})
    assert client.put(url, json={"template": "classic", "overrides": overrides}).status_code == 422
    assert client.get(url).json()["overrides"] == {"size": 60}


@pytest.mark.parametrize("overrides", BAD)
def test_bad_values_already_saved_dont_stop_a_project_from_opening(client, project, clip, overrides):
    with client.app.state.db.connect() as conn:
        conn.execute("UPDATE caption_styles SET options_json = ? WHERE project_id = ?", (json.dumps(overrides), project["id"]))
    res = client.get(f"/projects/{project['id']}/caption-style")
    assert res.status_code == 200
    style = res.json()["style"]
    assert 24 <= style["size"] <= 200 and style["color"].startswith("#") and len(style["color"]) == 7
    assert client.get(f"/clips/{clip['id']}/captions").status_code == 200


def test_good_style_values_are_kept(client, project):
    good = {"font": "Arial", "size": 72, "uppercase": True, "color": "#00ff00", "highlight": "", "position": "top"}
    body = client.put(f"/projects/{project['id']}/caption-style", json={"template": "classic", "overrides": good}).json()
    assert body["overrides"] == good and {k: body["style"][k] for k in good} == good


# --- filler words are language specific (F-13) ---------------------------------------------------


@pytest.mark.parametrize("language, removed", [("en", True), ("pt", False), ("de", False), ("bn", False), (None, False)])
def test_fillers_are_only_removed_from_english(client, project, clip, language, removed):
    path = client.app.state.ingest.source_dir(project["id"], clip["source_id"]) / "transcript.json"
    data = json.loads(path.read_text()) | {"language": language}
    path.write_text(json.dumps(data))
    tighten(client, clip)
    plan = client.get(f"/clips/{clip['id']}/cut-plan").json()
    assert (plan["fillers"] > 0) == removed and (plan["removed_ms"] > 0) == removed
    assert ("Um, hello there friend." in texts(client, clip)) != removed


# --- deleting captions (F-09) --------------------------------------------------------------------


def test_every_caption_can_be_deleted_and_stays_deleted(client, clip):
    assert texts(client, clip) == ["Um, hello there friend.", "Second uh line.", "Last words."]
    edit(client, clip, cues(client, clip)[0], "")
    assert texts(client, clip) == ["Second uh line.", "Last words."]
    edit(client, clip, cues(client, clip)[-1], "")
    assert texts(client, clip) == ["Second uh line."]
    edit(client, clip, cues(client, clip)[0], "")
    assert texts(client, clip) == []
    assert client.get(f"/clips/{clip['id']}/captions").json()["status"] == "ready"
    client.delete(f"/clips/{clip['id']}/captions")
    assert len(texts(client, clip)) == 3


def test_extending_a_clip_still_fills_in_from_the_transcript(client, clip):
    client.patch(f"/clips/{clip['id']}", json={"end_ms": 6000})
    edit(client, clip, cues(client, clip)[0], "")
    assert texts(client, clip) == ["Second uh line."]
    client.patch(f"/clips/{clip['id']}", json={"end_ms": 10000})
    assert texts(client, clip) == ["Second uh line.", "Last words."]


def test_edits_saved_by_an_older_version_still_work(client, clip):
    old = [{**x, "text": x["text"].upper()} for x in WORDS[4:7]]
    with client.app.state.db.connect() as conn:
        conn.execute("INSERT INTO clip_captions (clip_id, words_json) VALUES (?, ?)", (clip["id"], json.dumps(old)))
    assert texts(client, clip) == ["Um, hello there friend.", "SECOND UH LINE.", "Last words."]


# --- edits outside the current range (F-10) ------------------------------------------------------


def test_editing_a_trimmed_clip_keeps_earlier_edits_elsewhere(client, clip):
    edit(client, clip, cues(client, clip)[-1], "FINAL EDIT")
    client.patch(f"/clips/{clip['id']}", json={"end_ms": 6000})
    edit(client, clip, cues(client, clip)[0], "X Y Z W")
    assert texts(client, clip) == ["X Y Z W Second uh", "line."] or texts(client, clip)[0].startswith("X Y Z W")
    client.patch(f"/clips/{clip['id']}", json={"end_ms": 10000})
    assert texts(client, clip)[-1] == "FINAL EDIT" and texts(client, clip)[0].startswith("X Y Z W")


def test_a_caption_deleted_outside_the_current_range_stays_deleted(client, clip):
    edit(client, clip, cues(client, clip)[-1], "")
    client.patch(f"/clips/{clip['id']}", json={"end_ms": 6000})
    edit(client, clip, cues(client, clip)[0], "Hello again my friend.")
    client.patch(f"/clips/{clip['id']}", json={"end_ms": 10000})
    assert texts(client, clip) == ["Hello again my friend.", "Second uh line."]


def test_a_word_cut_by_the_clips_edge_gets_its_full_length_back(client, clip):
    client.patch(f"/clips/{clip['id']}", json={"end_ms": 2000})  # inside "friend."
    edit(client, clip, cues(client, clip)[0], "Um, hello there FRIEND.")
    client.patch(f"/clips/{clip['id']}", json={"end_ms": 10000})
    word = cues(client, clip)[0]["words"][-1]
    assert (word["text"], word["end"]) == ("FRIEND.", 2200)
