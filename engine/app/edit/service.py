"""Building a clip's cut plan from its Tighten settings, the transcript and the audio levels."""

import json
from pathlib import Path
from typing import Any

from .. import ffmpeg, sources
from ..analysis.signals import LOUDNESS_PER_SECOND, cached_loudness, silence_threshold
from ..captions.cues import words_for_clip
from ..captions.service import ensure_transcript, load_transcript
from ..config import Settings
from .cutplan import CutPlan, TightenSettings, plan_cuts, quiet_share_from_levels


def tighten_settings(clip: Any) -> TightenSettings | None:
    edit = json.loads(clip["edit_json"] or "{}")
    return TightenSettings.from_dict(edit.get("tighten"))


def plan_for_clip(
    settings: Settings,
    clip: Any,
    source: Any,
    tighten: TightenSettings,
    cancel=None,
    transcribe_if_needed: bool = False,
) -> CutPlan | None:
    """The clip's cut plan, or None when there's no transcript (and transcribing wasn't asked for)."""
    transcript = load_transcript(settings, source["project_id"], source["id"])
    if transcript is None:
        if not transcribe_if_needed:
            return None
        transcript = ensure_transcript(settings, source, cancel)
    tools = ffmpeg.detect(settings.bin_dir)
    work_dir = sources.source_dir(settings, source["project_id"], source["id"])
    levels = cached_loudness(tools.ffmpeg.path, Path(source["proxy_path"]), work_dir, source["duration_ms"], bool(source["has_audio"]))
    quiet = quiet_share_from_levels(levels, silence_threshold(levels), LOUDNESS_PER_SECOND)
    words = words_for_clip(transcript["words"], clip["start_ms"], clip["end_ms"])
    return plan_cuts(words, clip["start_ms"], clip["end_ms"], quiet, tighten, source["fps"] or 30)
