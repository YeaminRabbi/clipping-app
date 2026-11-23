"""Which parts of a clip to cut out: filler words ("um", "uh") and long pauses. Times are source ms.

Cuts land on frame boundaries and never inside a kept word. A pause is only shortened when it's actually
quiet, so laughter, music or a sound effect between words is kept.
"""

import math
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

FILLERS = {"um", "umm", "uh", "uhh", "uhm", "er", "erm", "ah", "ahh", "hmm", "hm", "mm", "mhm"}
WORD_GUARD_MS = 20  # never cut closer than this to a kept word
FILLER_PAD_MS = 40  # take a little air with each filler
QUIET_SHARE = 0.8  # a gap counts as a pause when this share of it is below the silence level
MIN_CUT_MS = 120  # shorter cuts aren't worth the jump
DEGENERATE_FILLER_MS = 100  # Whisper gives some short fillers (a quick "uh") almost no duration at all
FILLER_FALLBACK_MS = 300  # how much to cut around such a filler when its neighbours leave lots of room
MAX_GAP_CUT_MS = 700  # ... and if the room is no bigger than this, the filler fills it: cut the whole gap
DEFAULT_MAX_PAUSE_MS = 500


@dataclass(frozen=True)
class TightenSettings:
    remove_fillers: bool = True
    remove_pauses: bool = True
    max_pause_ms: int = DEFAULT_MAX_PAUSE_MS  # pauses longer than this are shortened to it

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "TightenSettings | None":
        """None when tightening is off for the clip."""
        if not data or not (data.get("remove_fillers") or data.get("remove_pauses")):
            return None
        return cls(
            remove_fillers=bool(data.get("remove_fillers")),
            remove_pauses=bool(data.get("remove_pauses")),
            max_pause_ms=int(min(max(int(data.get("max_pause_ms", DEFAULT_MAX_PAUSE_MS)), 150), 3000)),
        )


@dataclass
class Cut:
    start: float
    end: float
    reason: str  # "filler" | "pause"


@dataclass
class CutPlan:
    segments: list[tuple[float, float]]  # kept parts, frame-aligned source ms
    cuts: list[Cut] = field(default_factory=list)
    fillers: int = 0
    pauses: int = 0

    @property
    def duration_ms(self) -> float:
        return sum(b - a for a, b in self.segments)

    def to_dict(self, clip_length_ms: int) -> dict[str, Any]:
        return {
            "segments": [[round(a, 3), round(b, 3)] for a, b in self.segments],
            "cuts": [{"start": round(c.start, 3), "end": round(c.end, 3), "reason": c.reason} for c in self.cuts],
            "fillers": self.fillers,
            "pauses": self.pauses,
            "duration_ms": round(self.duration_ms),
            "removed_ms": round(clip_length_ms - self.duration_ms),
        }


def is_filler(text: str) -> bool:
    return re.sub(r"[^\w]", "", text.lower()) in FILLERS


def _snap(ms: float, fps: float, up: bool) -> float:
    """To a frame boundary: inward for cuts, so a cut never grows into a kept word."""
    frame = math.ceil(ms * fps / 1000 - 1e-6) if up else math.floor(ms * fps / 1000 + 1e-6)
    return frame * 1000 / fps


def plan_cuts(
    words: list[dict[str, Any]],
    start_ms: int,
    end_ms: int,
    quiet_share: Callable[[float, float, list[tuple[float, float]]], float],
    settings: TightenSettings,
    fps: float,
) -> CutPlan:
    """`words` are the clip's words (clamped to it). `quiet_share(a, b, ignore)` is the fraction of
    [a, b) that's silent, not counting the `ignore` ranges (parts already being cut)."""
    # The clip's own edges sit on the nearest frames, exactly as export renders them.
    clip_start = round(start_ms * fps / 1000) * 1000 / fps
    clip_end = round(end_ms * fps / 1000) * 1000 / fps
    raw: list[Cut] = []

    kept = words
    if settings.remove_fillers:
        kept = []
        for i, w in enumerate(words):
            if not is_filler(w["text"]):
                kept.append(w)
                continue
            lo = words[i - 1]["end"] + WORD_GUARD_MS if i > 0 else clip_start
            hi = words[i + 1]["start"] - WORD_GUARD_MS if i + 1 < len(words) else clip_end
            start, end = w["start"] - FILLER_PAD_MS, w["end"] + FILLER_PAD_MS
            if w["end"] - w["start"] < DEGENERATE_FILLER_MS:
                # We don't know where the sound really is, only roughly where. In a tight gap it is the gap.
                mid = (w["start"] + w["end"]) / 2
                start, end = (lo, hi) if hi - lo <= MAX_GAP_CUT_MS else (mid - FILLER_FALLBACK_MS / 2, mid + FILLER_FALLBACK_MS / 2)
            raw.append(Cut(max(lo, start), min(hi, end), "filler"))

    if settings.remove_pauses and kept:
        keep_half = settings.max_pause_ms / 2
        gaps = [(a["end"], b["start"]) for a, b in zip(kept, kept[1:])]
        # Silence before the first word and after the last is trimmed the same way.
        gaps = [(clip_start - keep_half, kept[0]["start"])] + gaps + [(kept[-1]["end"], clip_end + keep_half)]
        filler_ranges = [(c.start, c.end) for c in raw]
        for a, b in gaps:
            if b - a <= settings.max_pause_ms:
                continue
            lo, hi = max(a + keep_half, clip_start), min(b - keep_half, clip_end)
            if hi - lo >= MIN_CUT_MS and quiet_share(max(a, clip_start), min(b, clip_end), filler_ranges) >= QUIET_SHARE:
                raw.append(Cut(lo, hi, "pause"))

    # Snap inward to frames, merge overlaps, and drop cuts too short to matter.
    cuts: list[Cut] = []
    for cut in sorted(raw, key=lambda c: c.start):
        s, e = _snap(cut.start, fps, up=True), _snap(cut.end, fps, up=False)
        if e - s < MIN_CUT_MS:
            continue
        if cuts and s <= cuts[-1].end + 1e-6:
            prev = cuts[-1]
            prev.end = max(prev.end, e)
            if cut.reason == "filler":
                prev.reason = "filler"
            continue
        cuts.append(Cut(s, e, cut.reason))

    segments: list[tuple[float, float]] = []
    cursor = clip_start
    min_keep = 2 * 1000 / fps
    for cut in cuts:
        if cut.start - cursor >= min_keep:
            segments.append((cursor, cut.start))
        cursor = max(cursor, cut.end)
    if clip_end - cursor >= min_keep:
        segments.append((cursor, clip_end))
    if not segments:  # never cut a clip down to nothing
        segments, cuts = [(clip_start, clip_end)], []

    # Count what is actually removed: a candidate that was too short to cut doesn't count.
    def removed(kind: str) -> int:
        return sum(1 for r in raw if r.reason == kind and any(r.start < c.end and c.start < r.end for c in cuts))

    return CutPlan(segments=segments, cuts=cuts, fillers=removed("filler"), pauses=removed("pause"))


def quiet_share_from_levels(levels, threshold: float, per_second: int):
    """quiet_share() for plan_cuts, from loudness levels (dB per 1/per_second s)."""

    def share(a: float, b: float, ignore: list[tuple[float, float]]) -> float:
        step = 1000 / per_second
        counted = quiet = 0
        t = a
        while t < b:
            if not any(lo <= t < hi for lo, hi in ignore):
                i = min(len(levels) - 1, max(0, int(t / step)))
                counted += 1
                quiet += levels[i] < threshold
            t += step
        return quiet / counted if counted else 1.0

    return share
