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
    and pauses so a cue never straddles two thoughts. Words that already carry an `index` keep it."""
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
        current.append({**word, "index": word.get("index", i)})
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

    Same number of words: each keeps its own timing. Otherwise the cue's time is shared out in
    proportion to word length. Empty text deletes the words. Words between the indices that the cue
    doesn't show (fillers Tighten cuts) are left as they are, and new words never land on them.
    """
    if not indices:
        return words
    tokens = new_text.split()
    if len(tokens) == len(indices):
        out = list(words)
        for i, token in zip(indices, tokens):
            out[i] = {**out[i], "text": token}
        return out
    first, last = indices[0], indices[-1]
    chosen = set(indices)
    hidden = [words[i] for i in range(first, last + 1) if i not in chosen]
    middle = sorted(hidden + _spread(tokens, _runs(words, indices)), key=lambda w: w["start"])
    return words[:first] + middle + words[last + 1 :]


def _runs(words: list[dict[str, Any]], indices: list[int]) -> list[tuple[float, float]]:
    """(start, end) of each stretch of neighbouring indices."""
    runs: list[tuple[float, float]] = []
    previous = None
    for i in indices:
        if previous is not None and i == previous + 1:
            runs[-1] = (runs[-1][0], words[i]["end"])
        else:
            runs.append((words[i]["start"], words[i]["end"]))
        previous = i
    return runs


def _spread(tokens: list[str], runs: list[tuple[float, float]]) -> list[dict[str, Any]]:
    """Time `tokens` over the runs, skipping the gaps between them."""
    if not tokens:
        return []
    total_chars = sum(len(t) for t in tokens)
    total_time = sum(b - a for a, b in runs)
    out, position = [], 0.0
    for token in tokens:
        span = total_time * len(token) / total_chars
        # The run the token's middle falls in; the token stays inside it.
        offset = 0.0
        for a, b in runs:
            if position + span / 2 <= offset + (b - a) or (a, b) == runs[-1]:
                start, end = max(a, a + position - offset), min(b, a + position + span - offset)
                break
            offset += b - a
        out.append({"start": round(start), "end": round(end), "text": token})
        position += span
    out[-1]["end"] = runs[-1][1]
    return out


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
