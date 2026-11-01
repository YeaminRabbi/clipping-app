"""Putting the pieces together: candidates for the chosen mode, snapping, scoring and selection."""

from dataclasses import dataclass, field

from .candidates import Candidate, even_candidates, sentences, snap, talking_candidates, window_candidates
from .scoring import Signals, auto_count, score_candidates, select, title_for

POOL_SIZE = 300  # alternates kept for "Replace this clip"


@dataclass
class FindSettings:
    mode: str  # talking | action | even
    count: int | None  # None = auto
    min_ms: int
    max_ms: int
    lo: int
    hi: int
    keywords: list[str] = field(default_factory=list)


@dataclass
class FindResult:
    chosen: list[Candidate]
    pool: list[Candidate]
    mode_used: str
    notes: list[str]


def find_clips(s: FindSettings, sig: Signals, duration_ms: int, taken: list[tuple[int, int]]) -> FindResult:
    notes: list[str] = []
    mode = s.mode
    target = (s.min_ms + s.max_ms) // 2
    count = s.count or auto_count(s.hi - s.lo, target)

    if mode == "even":
        cands = even_candidates(count, s.min_ms, s.max_ms, s.lo, s.hi)
    elif mode == "talking":
        cands = talking_candidates(sentences(sig.words), s.min_ms, s.max_ms, s.lo, s.hi)
        if not cands:
            notes.append(
                "No speech that fits the clip length was found, so clips were picked by energy and scene changes."
                if sig.words
                else "No speech was found, so clips were picked by energy and scene changes."
            )
            mode = "action"
    if mode == "action":
        anchors = sorted(set(sig.cuts) | {e for _, e in sig.silences})
        cands = window_candidates(duration_ms, s.min_ms, s.max_ms, s.lo, s.hi, anchors)

    for cand in cands:
        snap(cand, sig.words, sig.cuts, sig.silences, duration_ms)
    cands = [c for c in cands if c.duration > 0]
    score_candidates(cands, sig, mode, s.keywords)

    chosen = cands if mode == "even" else select(cands, count, taken)
    if mode == "even":
        chosen = [c for c in chosen if not any(c.overlaps(a, b) for a, b in taken)]
    for i, cand in enumerate(chosen, start=1):
        cand.title = title_for(cand, i, mode)
    if s.count and len(chosen) < s.count:
        notes.append(f"Only {len(chosen)} clip{'s' if len(chosen) != 1 else ''} fit without overlapping (you asked for {s.count}).")

    pool = sorted(cands, key=lambda c: -c.score)[:POOL_SIZE]
    for cand in pool:
        if not cand.title:
            cand.title = title_for(cand, 0, mode) if mode == "talking" else "Highlight"
    return FindResult(chosen=chosen, pool=pool, mode_used=mode, notes=notes)


def next_alternate(pool: list[dict], taken: list[tuple[int, int]], skip: set[tuple[int, int]]) -> dict | None:
    """Best pooled candidate that doesn't overlap existing clips and wasn't shown before."""
    for cand in pool:  # already sorted best first
        key = (cand["start"], cand["end"])
        if key in skip:
            continue
        if any(cand["start"] < e and s < cand["end"] for s, e in taken):
            continue
        return cand
    return None
