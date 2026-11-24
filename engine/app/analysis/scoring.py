"""Rule-based scoring of candidate clips and choosing the final set.

Each candidate gets features in 0..1, a weighted sum per mode becomes a 0-100 score, and the
strongest contributions become the human-readable reasons shown in the app.
"""

import re
from dataclasses import dataclass

import numpy as np

from .candidates import Candidate, words_in
from .engagement import text_features
from .signals import LOUDNESS_PER_SECOND

WEAK_STARTS = {"and", "but", "so", "because", "or", "then", "also", "anyway", "plus", "which", "um", "uh"}
# Weights per mode. Positive weights add up to 1 so a perfect clip scores 100.
WEIGHTS: dict[str, dict[str, float]] = {
    "talking": {
        "keywords": 0.15, "hook": 0.22, "density": 0.10, "energy": 0.08,
        "complete": 0.10, "payoff": 0.12, "contrast": 0.08, "coverage": 0.10, "peaks": 0.05,
        "silence": -0.40, "weak_start": -0.15, "intro": -0.20,
        "promo": -0.20, "repetition": -0.25, "slow_start": -0.15,
    },
    "action": {
        "energy": 0.25, "peaks": 0.25, "scenes": 0.20, "keywords": 0.15, "clean": 0.10, "density": 0.05,
        "silence": -0.40,
    },
}  # fmt: skip

REASON_LABELS = {
    "hook": "strong opening line",
    "density": "fast-paced talking",
    "energy": "high energy",
    "peaks": "loud moments",
    "complete": "complete thought",
    "payoff": "conclusion or takeaway cue",
    "contrast": "contrast or surprise cue",
    "coverage": "sustained speech",
    "scenes": "lots of action",
    "clean": "clean scene boundaries",
}


@dataclass
class Signals:
    words: list[dict]
    loudness: np.ndarray  # dB per 100 ms
    cuts: list[int]
    silences: list[tuple[int, int]]


def _keyword_patterns(keywords: list[str]) -> list[tuple[str, re.Pattern]]:
    return [(k, re.compile(r"\b" + re.escape(k.lower()) + r"\b")) for k in keywords if k.strip()]


def _overlap_ms(spans: list[tuple[int, int]], start: int, end: int) -> int:
    return sum(max(0, min(e, end) - max(s, start)) for s, e in spans)


def features(
    cand: Candidate, sig: Signals, keywords: list[tuple[str, re.Pattern]], loud_ref: tuple[float, float]
) -> tuple[dict[str, float], list[str]]:
    """Feature values in 0..1, plus which keywords matched."""
    seconds = max(cand.duration / 1000, 0.1)
    i0 = int(cand.start / 1000 * LOUDNESS_PER_SECOND)
    i1 = max(i0 + 1, int(cand.end / 1000 * LOUDNESS_PER_SECOND))
    levels = sig.loudness[i0:i1] if len(sig.loudness) else np.array([-90.0])
    p50, p90 = loud_ref
    mean_db = float(np.mean(levels)) if len(levels) else -90.0

    words = words_in(sig.words, cand.start, cand.end)
    text = (cand.text or " ".join(w["text"] for w in words)).lower()
    first_word = re.sub(r"[^\w']", "", words[0]["text"].lower()) if words else ""
    # A hook late in a long sentence cannot rescue a slow opening. Use actual word timings.
    opening_words = [w for w in words if w["start"] < cand.start + 3000]
    ending_words = [w for w in words if w["end"] > cand.end - 6000]
    opening = " ".join(w["text"] for w in opening_words)
    ending = " ".join(w["text"] for w in ending_words)
    spoken_ms = sum(max(0, min(w["end"], cand.end) - max(w["start"], cand.start)) for w in words)
    delay = max(0, words[0]["start"] - cand.start) if words else 0

    hits = [k for k, pattern in keywords if pattern.search(text)]
    f = {
        # Mostly relative energy, with a small audibility baseline so steady sound beats silence.
        "energy": float(0.9 * np.clip((mean_db - p50) / max(p90 - p50, 1.0), 0, 1)
                        + 0.1 * np.clip((mean_db + 60) / 40, 0, 1)),
        # Flat audio is not a highlight just because every sample equals its 90th percentile.
        "peaks": float(np.mean(levels >= p90)) * 2 if len(levels) and p90 - p50 >= 1 else 0.0,
        "density": min(1.0, len(words) / seconds / 3.0),
        "scenes": min(1.0, sum(1 for c in sig.cuts if cand.start < c < cand.end) / seconds * 2),
        "keywords": min(1.0, len(hits) / 2),
        "complete": 1.0 if text.rstrip().endswith((".", "!", "?")) else 0.0,
        "coverage": min(1.0, spoken_ms / max(cand.duration, 1) / 0.65),
        "slow_start": min(1.0, delay / 2000),
        "silence": _overlap_ms(sig.silences, cand.start, cand.end) / max(cand.duration, 1),
        "weak_start": 1.0 if first_word in WEAK_STARTS else 0.0,
        "clean": (0.5 if cand.clean_start else 0.0) + (0.5 if cand.clean_end else 0.0),
    }
    f.update(text_features(text, opening, ending))
    f["peaks"] = min(1.0, f["peaks"])
    return f, hits


def score_candidates(cands: list[Candidate], sig: Signals, mode: str, keywords: list[str]) -> None:
    weights = dict(WEIGHTS["talking" if mode == "talking" else "action"])
    patterns = _keyword_patterns(keywords)
    if not patterns:
        # Without keywords, share their weight among the other positive features.
        share = weights.pop("keywords")
        positive = {k: v for k, v in weights.items() if v > 0}
        total = sum(positive.values())
        for k in positive:
            weights[k] += share * positive[k] / total
    audible = sig.loudness[sig.loudness > -89] if len(sig.loudness) else np.array([])
    loud_ref = (float(np.percentile(audible, 50)), float(np.percentile(audible, 90))) if len(audible) else (-60.0, -20.0)

    for cand in cands:
        f, hits = features(cand, sig, patterns, loud_ref)
        contributions = {k: w * f[k] for k, w in weights.items()}
        cand.score = round(float(np.clip(sum(contributions.values()), 0, 1)) * 100, 1)
        reasons = [f"keyword: {h}" for h in hits[:2]]
        top = sorted((c, k) for k, c in contributions.items() if c > 0.04 and k in REASON_LABELS)
        reasons += [REASON_LABELS[k] for _, k in reversed(top)][: 3 - len(reasons)]
        if f["weak_start"] and mode == "talking":
            reasons.append("starts mid-thought")
        if mode == "talking":
            for key, label in (("intro", "intro before the main point"), ("promo", "promotional segment"),
                               ("repetition", "repeated speech"), ("slow_start", "slow opening")):
                if f[key] >= 0.5:
                    reasons.append(label)
        cand.reasons = reasons


def auto_count(span_ms: int, target_ms: int) -> int:
    """How many clips "Auto" asks for: roughly one per four clip-lengths of video, 1 to 30."""
    return int(min(30, max(1, round(span_ms / max(target_ms, 1) / 4))))


def select(cands: list[Candidate], count: int, taken: list[tuple[int, int]]) -> list[Candidate]:
    """Best-scoring candidates that don't overlap each other or clips the user already has."""
    chosen: list[Candidate] = []
    blocked = list(taken)
    # Ties go to the earlier, then shorter, clip so results are stable between runs.
    for cand in sorted(cands, key=lambda c: (-c.score, c.start, c.duration)):
        if len(chosen) >= count:
            break
        if any(cand.overlaps(s, e) for s, e in blocked):
            continue
        chosen.append(cand)
        blocked.append((cand.start, cand.end))
    return sorted(chosen, key=lambda c: c.start)


def title_for(cand: Candidate, index: int, mode: str, max_words: int = 7) -> str:
    if cand.title:
        return cand.title
    if mode == "talking" and cand.sentences:
        words = cand.sentences[0].rstrip(".!?…,").split()
        return " ".join(words[:max_words])
    return f"Highlight {index}"
