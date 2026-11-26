"""The source ranges of a clip, in playback order, optionally tightened inside each range."""

import json

from .cutplan import TightenSettings
from .service import plan_for_clip


def clip_segments(clip) -> list[tuple[int, int]]:
    edit = json.loads(clip["edit_json"] or "{}")
    return [(s["start_ms"], s["end_ms"]) for s in edit.get("segments") or []] or [(clip["start_ms"], clip["end_ms"])]


def kept_segments(settings, clip, source, tighten: TightenSettings | None, cancel=None, transcribe=False):
    segments = clip_segments(clip)
    if tighten is None:
        return segments
    kept = []
    for a, b in segments:
        part = {**dict(clip), "start_ms": a, "end_ms": b}
        plan = plan_for_clip(settings, part, source, tighten, cancel, transcribe_if_needed=transcribe)
        if plan is None:
            return None
        kept.extend(plan.segments)
    return kept
