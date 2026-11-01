"""Output aspect ratios and crop geometry.

Crops are stored as rectangles normalized to the source's displayed frame (0..1, after rotation), so
they don't depend on the proxy or original resolution.
"""

from dataclasses import dataclass
from fractions import Fraction


@dataclass(frozen=True)
class Aspect:
    key: str  # "9:16"
    label: str
    ratio: Fraction  # width / height


ASPECTS: dict[str, Aspect] = {
    a.key: a
    for a in [
        Aspect("9:16", "Phone (Reels / TikTok / Shorts)", Fraction(9, 16)),
        Aspect("4:5", "Instagram portrait", Fraction(4, 5)),
        Aspect("1:1", "Instagram square", Fraction(1, 1)),
        Aspect("16:9", "Desktop / YouTube", Fraction(16, 9)),
        Aspect("4:3", "Tablet", Fraction(4, 3)),
    ]
}

RESOLUTIONS = (1080, 720)


def _even(value: float) -> int:
    return max(2, int(round(value / 2)) * 2)


def output_size(aspect: str, short_side: int = 1080) -> tuple[int, int]:
    """1080 short side: 9:16 -> 1080x1920, 16:9 -> 1920x1080, 4:3 -> 1440x1080."""
    ratio = ASPECTS[aspect].ratio
    if ratio < 1:
        return short_side, _even(short_side / ratio)
    return _even(short_side * ratio), short_side


def default_crop(aspect: str, src_w: int, src_h: int) -> dict[str, float]:
    """Largest centered rectangle of the target aspect."""
    target = float(ASPECTS[aspect].ratio)
    src = src_w / src_h
    if target < src:
        w, h = target / src, 1.0
    else:
        w, h = 1.0, src / target
    return {"x": (1 - w) / 2, "y": (1 - h) / 2, "w": w, "h": h}


def crop_path(keyframes: list[dict], aspect: str, src_w: int, src_h: int, seek_s: float):
    """Tracked keyframes (source ms, normalized) -> a pixel CropPath timed from the render's seek point."""
    from .media.render import CropPath

    w, h, _, _ = crop_pixels(keyframes[0], aspect, src_w, src_h)
    points: list[tuple[float, int, int]] = []
    for kf in keyframes:
        x = min(max(0, round(kf["x"] * src_w)), src_w - w)
        y = min(max(0, round(kf["y"] * src_h)), src_h - h)
        points.append((kf["t"] / 1000 - seek_s, x, y))
    return CropPath(w=w, h=h, points=points)


def crop_pixels(crop: dict[str, float], aspect: str, src_w: int, src_h: int) -> tuple[int, int, int, int]:
    """Normalized crop -> even pixel (w, h, x, y) inside the frame, with the exact target aspect."""
    ratio = float(ASPECTS[aspect].ratio)
    w = min(crop["w"] * src_w, src_w)
    h = w / ratio
    if h > src_h:
        h = src_h
        w = h * ratio
    cw, ch = min(_even(w), src_w - src_w % 2), min(_even(h), src_h - src_h % 2)
    x = min(max(0, round(crop["x"] * src_w)), src_w - cw)
    y = min(max(0, round(crop["y"] * src_h)), src_h - ch)
    return cw, ch, x - x % 2, y - y % 2
