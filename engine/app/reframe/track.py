"""From face detections to a smooth, shot-aware crop path (pure functions, times in ms).

The look we aim for is a steady camera operator: within a shot the crop holds still unless the
subject really moves, moves are smooth, and at a scene cut the crop jumps instead of panning.
"""

import statistics
from dataclasses import dataclass

from .detect import Face

FOLLOW_RADIUS = 0.15  # stick with the same face if it stays within this distance between samples
MIN_AREA_RATIO = 0.5  # ... and isn't much smaller than the biggest face
HOLD_STILL_RANGE = 0.35  # if the subject moves less than this share of the crop width, don't move at all
SMOOTH_WINDOW = 7  # samples (~1.4 s at 5 fps) for the moving average
MAX_SPEED = 0.35  # crop width per second, so pans never whip
HEADROOM = 0.12  # face sits this much above the crop's vertical center
SIMPLIFY_TOLERANCE = 0.002  # ~4 px at 1920 wide; path points closer than this to a line are dropped


@dataclass
class Keyframe:
    t: int  # source time, ms
    x: float
    y: float
    w: float
    h: float

    def as_dict(self) -> dict:
        return {"t": self.t, "x": round(self.x, 5), "y": round(self.y, 5), "w": round(self.w, 5), "h": round(self.h, 5)}


def choose_subject(samples: list[tuple[int, list[Face]]]) -> list[tuple[int, Face | None]]:
    """One face per sample: the biggest, unless the face we were following is still there."""
    out: list[tuple[int, Face | None]] = []
    prev: Face | None = None
    for t, faces in samples:
        if not faces:
            out.append((t, None))
            continue
        biggest = max(faces, key=lambda f: f.area)
        pick = biggest
        if prev is not None:
            near = [
                f for f in faces
                if abs(f.cx - prev.cx) < FOLLOW_RADIUS and abs(f.cy - prev.cy) < FOLLOW_RADIUS
                and f.area >= biggest.area * MIN_AREA_RATIO
            ]  # fmt: skip
            if near:
                pick = min(near, key=lambda f: abs(f.cx - prev.cx) + abs(f.cy - prev.cy))
        out.append((t, pick))
        prev = pick
    return out


def _median_filter(values: list[float], k: int = 5) -> list[float]:
    half = k // 2
    return [statistics.median(values[max(0, i - half) : i + half + 1]) for i in range(len(values))]


def _moving_average(values: list[float], k: int) -> list[float]:
    half = k // 2
    return [sum(values[max(0, i - half) : i + half + 1]) / len(values[max(0, i - half) : i + half + 1]) for i in range(len(values))]


def _limit_speed(values: list[float], times: list[int], max_per_ms: float) -> list[float]:
    out = values[:1]
    for v, t0, t1 in zip(values[1:], times, times[1:]):
        step = max_per_ms * (t1 - t0)
        out.append(out[-1] + max(-step, min(step, v - out[-1])))
    return out


def _shot_path(points: list[tuple[int, float | None]], fallback: float, crop_size: float) -> list[float]:
    """Smooth one shot's subject positions (None = no face) into crop centers."""
    known = [v for _, v in points if v is not None]
    if not known:
        return [fallback] * len(points)
    # Fill gaps by holding the nearest known position.
    filled: list[float] = []
    last = known[0]
    for _, v in points:
        last = v if v is not None else last
        filled.append(last)
    filled = _median_filter(filled)  # drops one-off false detections
    if max(filled) - min(filled) < HOLD_STILL_RANGE * crop_size:
        return [statistics.median(filled)] * len(filled)
    times = [t for t, _ in points]
    smooth = _moving_average(filled, SMOOTH_WINDOW)
    return _limit_speed(smooth, times, MAX_SPEED * crop_size / 1000)


def _simplify(points: list[Keyframe]) -> list[Keyframe]:
    """Ramer-Douglas-Peucker on (t, x, y): keep only the points that bend the path.

    Iterative, since long clips have more samples than Python's recursion limit allows.
    """
    if len(points) <= 2:
        return points
    keep = {0, len(points) - 1}
    stack = [(0, len(points) - 1)]
    while stack:
        lo, hi = stack.pop()
        a, b = points[lo], points[hi]
        span = max(b.t - a.t, 1)
        worst, worst_i = 0.0, -1
        for i in range(lo + 1, hi):
            p = points[i]
            f = (p.t - a.t) / span
            d = max(abs(p.x - (a.x + (b.x - a.x) * f)), abs(p.y - (a.y + (b.y - a.y) * f)))
            if d > worst:
                worst, worst_i = d, i
        if worst > SIMPLIFY_TOLERANCE:
            keep.add(worst_i)
            stack += [(lo, worst_i), (worst_i, hi)]
    return [points[i] for i in sorted(keep)]


def camera_path(
    subject: list[tuple[int, Face | None]],
    cuts: list[int],
    crop: dict[str, float],
) -> tuple[list[Keyframe], float]:
    """Keyframes for a crop of fixed size following the subject, and the share of samples with a face.

    `crop` gives the size (w, h, normalized) and the fallback position used when no face is found.
    """
    if not subject:
        return [], 0.0
    w, h = crop["w"], crop["h"]
    found = [f for _, f in subject if f is not None]
    # Shots without faces fall back to where faces usually are in this clip, else the given crop.
    fallback_cx = statistics.median(f.cx for f in found) if found else crop["x"] + w / 2
    fallback_cy = statistics.median(f.cy for f in found) + HEADROOM * h if found else crop["y"] + h / 2

    # Split samples into shots at scene cuts, remembering each shot's cut time.
    shots: list[tuple[int | None, list[tuple[int, Face | None]]]] = [(None, [])]
    cut_iter = iter(sorted(c for c in cuts if subject[0][0] < c <= subject[-1][0]))
    next_cut = next(cut_iter, None)
    for t, f in subject:
        while next_cut is not None and t >= next_cut:
            if shots[-1][1]:
                shots.append((next_cut, []))
            next_cut = next(cut_iter, None)
        shots[-1][1].append((t, f))

    keyframes: list[Keyframe] = []
    for cut, shot in shots:
        xs = _shot_path([(t, f.cx if f else None) for t, f in shot], fallback_cx, w)
        ys = _shot_path([(t, f.cy + HEADROOM * h if f else None) for t, f in shot], fallback_cy, h)
        points = [
            Keyframe(t=t, x=min(max(cx - w / 2, 0.0), 1 - w), y=min(max(cy - h / 2, 0.0), 1 - h), w=w, h=h)
            for (t, _), cx, cy in zip(shot, xs, ys)
        ]
        simplified = _simplify(points)
        if keyframes and simplified and cut is not None:
            # Hold the previous shot's framing right up to the cut, then jump exactly at it.
            last = keyframes[-1]
            keyframes.append(Keyframe(t=cut - 1, x=last.x, y=last.y, w=w, h=h))
            simplified[0].t = min(simplified[0].t, cut)
        keyframes.extend(simplified)
    return keyframes, len(found) / len(subject)


def crop_at(keyframes: list[dict], t: float) -> dict[str, float]:
    """Linear interpolation of the crop at source time t (ms); holds the ends."""
    if t <= keyframes[0]["t"]:
        return keyframes[0]
    for a, b in zip(keyframes, keyframes[1:]):
        if t <= b["t"]:
            f = (t - a["t"]) / max(b["t"] - a["t"], 1)
            return {k: a[k] + (b[k] - a[k]) * f for k in ("x", "y", "w", "h")}
    return keyframes[-1]
