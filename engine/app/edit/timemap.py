"""Mapping source times onto a tightened clip, whose kept segments play back to back."""

from typing import Any


class TimeMap:
    def __init__(self, segments: list[tuple[float, float]]):
        self.segments = segments
        self._starts = [a for a, _ in segments]
        self._offsets: list[float] = []
        total = 0.0
        for a, b in segments:
            self._offsets.append(total)
            total += b - a
        self.duration = total

    def to_output(self, t: float) -> float | None:
        """Output time for source time t, or None if t falls in a removed part."""
        for (a, b), offset in zip(self.segments, self._offsets):
            if a <= t <= b:
                return offset + (t - a)
        return None

    def map_words(self, words: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Words that survive, re-timed to the output. A word is kept if its middle is kept."""
        out = []
        for (a, b), offset in zip(self.segments, self._offsets):
            for w in words:
                if a <= (w["start"] + w["end"]) / 2 < b:
                    out.append({**w, "start": round(offset + max(a, w["start"]) - a),
                                "end": round(offset + min(b, w["end"]) - a)})
        return out

    def map_keyframes(self, keyframes: list[dict[str, Any]], crop_at) -> list[dict[str, Any]]:
        """A smart-crop path re-timed to the output: each segment shows the path over that stretch,
        and the crop jumps at the joins (which are cuts in the edit)."""
        out: list[dict[str, Any]] = []
        for (a, b), offset in zip(self.segments, self._offsets):
            span = b - a
            points = [{**crop_at(keyframes, a), "t": offset}]
            points += [{**k, "t": offset + (k["t"] - a)} for k in keyframes if a < k["t"] < b]
            points.append({**crop_at(keyframes, b), "t": offset + span - 0.5})
            out += points
        return out
