"""Where caption words come from (the user's edits, else the transcript) and the project's style."""

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any

from .. import sources
from ..config import Settings
from .cues import Cue, make_cues, words_for_clip
from .styles import DEFAULT_TEMPLATE, CaptionStyle, resolve


_locks: dict[int, threading.Lock] = {}
_locks_guard = threading.Lock()


def transcript_lock(source_id: int) -> threading.Lock:
    """One transcription of a source at a time: exports of several sizes, and auto clipping, all need
    the same transcript, so later ones wait for the first and reuse it instead of redoing the work."""
    with _locks_guard:
        return _locks.setdefault(source_id, threading.Lock())


def transcript_path(settings: Settings, project_id: int, source_id: int) -> Path:
    return sources.source_dir(settings, project_id, source_id) / "transcript.json"


def load_transcript(settings: Settings, project_id: int, source_id: int) -> dict[str, Any] | None:
    path = transcript_path(settings, project_id, source_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    from ..analysis.transcribe import TRANSCRIPT_VERSION

    return data if data.get("version", 1) >= TRANSCRIPT_VERSION else None


def save_transcript(settings: Settings, source: Any, data: dict[str, Any]) -> None:
    """Write transcript.json atomically."""
    path = transcript_path(settings, source["project_id"], source["id"])
    tmp = path.with_suffix(".partial")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(path)


def ensure_transcript(settings: Settings, source: Any, cancel) -> dict[str, Any]:
    """The source's transcript, transcribing it now (balanced model) if it doesn't exist yet."""
    from .. import ffmpeg
    from ..analysis.transcribe import DEFAULT_MODEL, transcribe

    with transcript_lock(source["id"]):
        existing = load_transcript(settings, source["project_id"], source["id"])  # may have just been made
        if existing is not None:
            return existing
        if not source["has_audio"]:
            return {"model": DEFAULT_MODEL, "language": None, "words": []}
        tools = ffmpeg.detect(settings.bin_dir)
        data = transcribe(
            tools.ffmpeg.path, Path(source["proxy_path"]), source["duration_ms"], settings.models_path, DEFAULT_MODEL, None, cancel
        )
        save_transcript(settings, source, data)
        return data


def project_style(conn: sqlite3.Connection, project_id: int) -> tuple[str, dict[str, Any]]:
    row = conn.execute("SELECT template, options_json FROM caption_styles WHERE project_id = ?", (project_id,)).fetchone()
    if row is None:
        return DEFAULT_TEMPLATE, {}
    return row["template"], json.loads(row["options_json"] or "{}")


def resolved_style(conn: sqlite3.Connection, project_id: int) -> CaptionStyle:
    template, overrides = project_style(conn, project_id)
    return resolve(template, overrides)


def clip_words(conn: sqlite3.Connection, settings: Settings, clip: Any) -> tuple[list[dict[str, Any]] | None, bool]:
    """(words inside the clip, whether the user edited them). None when there's no transcript yet.

    Edited words are kept as they are; if the clip has since been extended, transcript words beyond the
    edited part fill in the rest, so trims never lose edits and extensions never leave gaps.
    """
    src = conn.execute("SELECT project_id FROM sources WHERE id = ?", (clip["source_id"],)).fetchone()
    transcript = load_transcript(settings, src["project_id"], clip["source_id"])
    row = conn.execute("SELECT words_json FROM clip_captions WHERE clip_id = ?", (clip["id"],)).fetchone()
    start, end = clip["start_ms"], clip["end_ms"]
    if row is None:
        if transcript is None:
            return None, False
        return words_for_clip(transcript["words"], start, end), False

    edited = words_for_clip(json.loads(row["words_json"]), start, end)
    if transcript is not None and edited:
        first, last = edited[0]["start"], edited[-1]["end"]
        extra = [w for w in words_for_clip(transcript["words"], start, end) if w["end"] <= first or w["start"] >= last]
        edited = sorted(edited + extra, key=lambda w: w["start"])
    return edited, True


def clip_cues(conn: sqlite3.Connection, settings: Settings, clip: Any) -> tuple[list[Cue] | None, bool, CaptionStyle]:
    src = conn.execute("SELECT project_id FROM sources WHERE id = ?", (clip["source_id"],)).fetchone()
    style = resolved_style(conn, src["project_id"])
    words, edited = clip_words(conn, settings, clip)
    if words is None:
        return None, False, style
    words = _without_cut_words(conn, settings, clip, words)
    return make_cues(words, style, end_limit=clip["end_ms"]), edited, style


def _without_cut_words(conn: sqlite3.Connection, settings: Settings, clip: Any, words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """When the clip is tightened, drop words that fall in removed parts (fillers), as the export does."""
    from ..edit.service import plan_for_clip, tighten_settings  # edit.service imports this module

    tighten = tighten_settings(clip)
    if tighten is None:
        return words
    source = conn.execute("SELECT * FROM sources WHERE id = ?", (clip["source_id"],)).fetchone()
    plan = plan_for_clip(settings, clip, source, tighten)
    if plan is None:
        return words
    return [w for w in words if not any(c.start <= (w["start"] + w["end"]) / 2 < c.end for c in plan.cuts)]
