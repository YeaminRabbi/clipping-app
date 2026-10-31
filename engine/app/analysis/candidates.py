"""Turning a transcript and signals into candidate clip windows with clean boundaries.

All times are milliseconds.
"""

import bisect
from dataclasses import dataclass, field
from typing import Any

SENTENCE_END = (".", "!", "?", "…")
# A pause this long ends a sentence even without punctuation (transcripts of casual speech often lack it).
SENTENCE_GAP_MS = 1200
LEAD_IN_MS = 150  # breathing room before the first word
TAIL_MS = 300  # and after the last, so words aren't clipped
SNAP_WINDOW_MS = 500
WORD_GUARD_MS = 20
WINDOW_GRID_MS = 2000


@dataclass
class Sentence:
    start: int
    end: int
    first_word: int  # index into the word list
    last_word: int
    text: str


@dataclass
class Candidate:
    start: int
    end: int
    first_word: int | None = None
    last_word: int | None = None
    text: str = ""
    sentences: list[str] = field(default_factory=list)
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    title: str = ""
    # Set by snap(): whether each edge landed on a scene cut or the edge of a silence.
    clean_start: bool = False
    clean_end: bool = False

    @property
    def duration(self) -> int:
        return self.end - self.start

    def overlaps(self, start: int, end: int) -> bool:
        return self.start < end and start < self.end

    def to_dict(self) -> dict[str, Any]:
        return {"start": self.start, "end": self.end, "score": self.score, "reasons": self.reasons, "title": self.title}


def sentences(words: list[dict[str, Any]]) -> list[Sentence]:
    out: list[Sentence] = []
    first = 0
    for i, word in enumerate(words):
        gap_after = words[i + 1]["start"] - word["end"] if i + 1 < len(words) else None
        if word["text"].endswith(SENTENCE_END) or gap_after is None or gap_after >= SENTENCE_GAP_MS:
            chunk = words[first : i + 1]
            out.append(Sentence(chunk[0]["start"], chunk[-1]["end"], first, i, " ".join(w["text"] for w in chunk)))
            first = i + 1
    return out


def talking_candidates(sents: list[Sentence], min_ms: int, max_ms: int, lo: int, hi: int) -> list[Candidate]:
    """Every run of whole sentences whose spoken length fits the range, inside [lo, hi]."""
    out: list[Candidate] = []
    for i, first in enumerate(sents):
        if first.start < lo:
            continue
        for j in range(i, len(sents)):
            last = sents[j]
            length = last.end - first.start
            if last.end > hi or length > max_ms:
                break
            if length >= min_ms:
                run = sents[i : j + 1]
                out.append(
                    Candidate(
                        start=first.start,
                        end=last.end,
                        first_word=first.first_word,
                        last_word=last.last_word,
                        text=" ".join(s.text for s in run),
                        sentences=[s.text for s in run],
                    )
                )
    return out


def window_candidates(duration_ms: int, min_ms: int, max_ms: int, lo: int, hi: int, anchors: list[int]) -> list[Candidate]:
    """Fixed-length windows starting at scene cuts, silence ends and a regular grid (for non-speech video)."""
    starts = sorted({lo, *range(lo, hi, WINDOW_GRID_MS), *(a for a in anchors if lo <= a < hi)})
    lengths = sorted({min_ms, (min_ms + max_ms) // 2, max_ms})
    out = []
    for start in starts:
        for length in lengths:
            end = start + length
            if end <= min(hi, duration_ms):
                out.append(Candidate(start=start, end=end))
    return out


def even_candidates(count: int, min_ms: int, max_ms: int, lo: int, hi: int) -> list[Candidate]:
    """`count` evenly spaced windows, each as long as the range allows."""
    span = hi - lo
    length = max(min_ms, min(max_ms, span // max(count, 1)))
    if length > span:
        length = span
    slot = span / max(count, 1)
    out = []
    for i in range(count):
        center = lo + slot * (i + 0.5)
        start = int(min(max(lo, center - length / 2), hi - length))
        out.append(Candidate(start=start, end=start + length, title=f"Part {i + 1}"))
    return out


def _nearest(points: list[int], target: int, lo: int, hi: int) -> int | None:
    """Closest point to target within [lo, hi]."""
    i = bisect.bisect_left(points, lo)
    best = None
    while i < len(points) and points[i] <= hi:
        if best is None or abs(points[i] - target) < abs(best - target):
            best = points[i]
        i += 1
    return best


def snap(
    cand: Candidate,
    words: list[dict[str, Any]],
    cuts: list[int],
    silences: list[tuple[int, int]],
    duration_ms: int,
) -> Candidate:
    """Move boundaries to natural points without ever cutting into a word.

    Speech: start just before the first word and end just after the last, then prefer a scene cut
    if one lies within half a second and doesn't clip any words. Non-speech: prefer a scene cut,
    else the edge of a silence.
    """
    if cand.first_word is not None and cand.last_word is not None:
        first, last = words[cand.first_word], words[cand.last_word]
        prev_end = words[cand.first_word - 1]["end"] + WORD_GUARD_MS if cand.first_word > 0 else 0
        next_start = (
            words[cand.last_word + 1]["start"] - WORD_GUARD_MS if cand.last_word + 1 < len(words) else duration_ms
        )
        start = max(prev_end, first["start"] - LEAD_IN_MS, 0)
        end = min(next_start, last["end"] + TAIL_MS, duration_ms)
        cut = _nearest(cuts, start, max(prev_end, start - SNAP_WINDOW_MS), min(first["start"], start + SNAP_WINDOW_MS))
        if cut is not None:
            start = cut
        cut = _nearest(cuts, end, max(last["end"], end - SNAP_WINDOW_MS), min(next_start, end + SNAP_WINDOW_MS))
        if cut is not None:
            end = cut
    else:
        silence_ends = [e for _, e in silences]
        silence_starts = [s for s, _ in silences]
        start = _nearest(cuts, cand.start, cand.start - SNAP_WINDOW_MS, cand.start + SNAP_WINDOW_MS)
        if start is None:
            start = _nearest(silence_ends, cand.start, cand.start - SNAP_WINDOW_MS, cand.start + SNAP_WINDOW_MS)
        end = _nearest(cuts, cand.end, cand.end - SNAP_WINDOW_MS, cand.end + SNAP_WINDOW_MS)
        if end is None:
            end = _nearest(silence_starts, cand.end, cand.end - SNAP_WINDOW_MS, cand.end + SNAP_WINDOW_MS)
        cand.clean_start, cand.clean_end = start is not None, end is not None
        start = max(0, cand.start if start is None else start)
        end = min(duration_ms, cand.end if end is None else end)
    cand.start, cand.end = start, end
    return cand


def words_in(words: list[dict[str, Any]], start: int, end: int) -> list[dict[str, Any]]:
    """Words spoken (mostly) within [start, end]."""
    return [w for w in words if w["start"] >= start - 50 and w["end"] <= end + 50]
