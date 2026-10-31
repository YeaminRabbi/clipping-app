"""Running smart reframing for a clip: sample frames, detect faces, build the crop path."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import ffmpeg
from ..analysis.signals import cached_scene_cuts
from ..aspects import default_crop
from ..config import Settings
from ..media import CancelToken, MediaError
from .detect import FaceDetector, sample_frames, video_size
from .track import camera_path, choose_subject

# Track a little beyond the clip so small trims don't need re-tracking.
MARGIN_MS = 3000


@dataclass
class TrackResult:
    keyframes: list[dict[str, Any]]
    face_ratio: float  # share of sampled frames with a face


def keyframes_cover(keyframes: list[dict], start_ms: int, end_ms: int) -> bool:
    """Whether a tracked path spans the clip (its first and last points mark the tracked range)."""
    return len(keyframes) >= 2 and keyframes[0]["t"] <= start_ms and keyframes[-1]["t"] >= end_ms


def track_clip(
    settings: Settings,
    source: Any,  # sources row
    work_dir: Path,
    start_ms: int,
    end_ms: int,
    aspect: str,
    cancel: CancelToken,
) -> TrackResult:
    tools = ffmpeg.detect(settings.bin_dir)
    proxy = Path(source["proxy_path"] or "")
    if not proxy.is_file():
        raise MediaError("The preview copy of this video is missing; re-import it")
    lo = max(0, start_ms - MARGIN_MS)
    hi = min(source["duration_ms"], end_ms + MARGIN_MS)

    width, height = video_size(tools.ffprobe.path, proxy)
    detector = FaceDetector(width, height)
    samples = [(t, detector.detect(frame)) for t, frame in sample_frames(tools.ffmpeg.path, proxy, width, height, lo, hi, cancel)]
    if not samples:
        raise MediaError("Could not read frames from this part of the video")
    # The last sample can fall just short of the range end; extend it so the path covers the clip.
    samples[-1] = (max(samples[-1][0], hi), samples[-1][1])

    cuts = cached_scene_cuts(tools.ffmpeg.path, proxy, work_dir, source["duration_ms"], cancel)
    keyframes, face_ratio = camera_path(choose_subject(samples), cuts, default_crop(aspect, source["width"], source["height"]))
    return TrackResult(keyframes=[k.as_dict() for k in keyframes], face_ratio=round(face_ratio, 3))
