"""Grouping words into on-screen cues, editing cue text, and SRT output. Times are source ms."""

from dataclasses import dataclass, field
from typing import Any

from .styles import CaptionStyle

SENTENCE_END = (".", "!", "?", "…")
PAUSE_BREAK_MS = 700  # a pause this long starts a new cue
HOLD_MS = 300  # keep a cue up a little after its last word, if the next one isn't starting
MIN_CUE_MS = 400


@dataclass
class Cue:
    start: int
    end: int
    words: list[dict[str, Any]] = field(default_factory=list)  # each has start, end, text, index

    @property
    def text(self) -> str:
        return " ".join(w["text"] for w in self.words)

    def to_dict(self) -> dict[str, Any]:
        return {"start": self.start, "end": self.end, "text": self.text, "words": self.words}


def words_for_clip(words: list[dict[str, Any]], start_ms: int, end_ms: int) -> list[dict[str, Any]]:
    """Words spoken inside the clip, clamped to its edges."""
    out = []
    for w in words:
        if w["end"] <= start_ms + 30 or w["start"] >= end_ms - 30:
            continue
        out.append({"start": max(w["start"], start_ms), "end": min(w["end"], end_ms), "text": w["text"]})
    return out


def make_cues(words: list[dict[str, Any]], style: CaptionStyle, end_limit: int | None = None) -> list[Cue]:
    """Split words into cues that fit the style's word and character limits, breaking at sentence ends
    and pauses so a cue never straddles two thoughts."""
    limit_chars = style.max_chars * style.max_lines
    cues: list[Cue] = []
    current: list[dict[str, Any]] = []
    for i, word in enumerate(words):
        if current:
            prev = current[-1]
            length = len(" ".join(w["text"] for w in current)) + 1 + len(word["text"])
            if (
                len(current) >= style.max_words
                or length > limit_chars
                or word["start"] - prev["end"] >= PAUSE_BREAK_MS
                or prev["text"].endswith(SENTENCE_END)
            ):
                cues.append(Cue(current[0]["start"], current[-1]["end"], current))
                current = []
        current.append({**word, "index": i})
    if current:
        cues.append(Cue(current[0]["start"], current[-1]["end"], current))

    # Hold each cue briefly after its last word, without overlapping the next cue.
    for i, cue in enumerate(cues):
        next_start = cues[i + 1].start if i + 1 < len(cues) else (end_limit if end_limit is not None else cue.end + HOLD_MS)
        cue.end = min(max(cue.end + HOLD_MS, cue.start + MIN_CUE_MS), next_start)
        cue.end = max(cue.end, cue.words[-1]["end"])
    return cues


def apply_text_edit(words: list[dict[str, Any]], indices: list[int], new_text: str) -> list[dict[str, Any]]:
    """Replace the words at `indices` (one cue) with `new_text`, keeping the cue's timing.

    Same number of words: each keeps its own timing. Otherwise the cue's time span is shared out in
    proportion to word length. Empty text deletes the words.
    """
    if not indices:
        return words
    old = [words[i] for i in indices]
    start, end = old[0]["start"], old[-1]["end"]
    tokens = new_text.split()
    if len(tokens) == len(old):
        replacement = [{**w, "text": t} for w, t in zip(old, tokens)]
    elif tokens:
        total = sum(len(t) for t in tokens)
        replacement, t = [], start
        for token in tokens:
            span = (end - start) * len(token) / total
            replacement.append({"start": round(t), "end": round(t + span), "text": token})
            t += span
        replacement[-1]["end"] = end
    else:
        replacement = []
    first, last = indices[0], indices[-1]
    return words[:first] + replacement + words[last + 1 :]


def wrap(text: str, max_chars: int, max_lines: int) -> str:
    """Balanced line breaks: no line much longer than max_chars, at most max_lines lines."""
    tokens = text.split()
    if len(text) <= max_chars or max_lines <= 1:
        return text
    best, best_score = text, None
    # Two lines: pick the break that makes the lines most even.
    for i in range(1, len(tokens)):
        a, b = " ".join(tokens[:i]), " ".join(tokens[i:])
        score = max(len(a), len(b))
        if best_score is None or score < best_score:
            best, best_score = f"{a}\n{b}", score
    return best


def _srt_time(ms: int) -> str:
    ms = max(0, ms)
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(cues: list[Cue], style: CaptionStyle, offset_ms: int) -> str:
    """SubRip text with times relative to `offset_ms` (the clip's start)."""
    blocks = []
    for n, cue in enumerate(cues, start=1):
        text = cue.text.upper() if style.uppercase else cue.text
        blocks.append(
            f"{n}\n{_srt_time(cue.start - offset_ms)} --> {_srt_time(cue.end - offset_ms)}\n"
            f"{wrap(text, style.max_chars, max(2, style.max_lines))}\n"
        )
    return "\n".join(blocks)
