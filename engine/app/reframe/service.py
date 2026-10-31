"""Running smart reframing for a clip: sample frames, detect faces, build the crop path."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from .. import ffmpeg
from ..analysis.signals import LOUDNESS_PER_SECOND, cached_scene_cuts, loudness, silence_threshold
from ..aspects import default_crop
from ..config import Settings
from ..media import CancelToken, MediaError
from .detect import FaceDetector, mouth_patch, sample_frames, video_size
from .speaker import MIN_TRACK_SHARE, assign_tracks, pick_speaker
from .track import camera_path, choose_subject

# Track a little beyond the clip so small trims don't need re-tracking.
MARGIN_MS = 3000
FOLLOW_MODES = ("speaker", "largest")


@dataclass
class TrackResult:
    keyframes: list[dict[str, Any]]
    face_ratio: float  # share of sampled frames with a face
    follow: str = "largest"  # what was actually followed: "speaker" needs two or more people on screen
    speakers: int = 0
    switches: list[int] = field(default_factory=list)

    def options(self, requested: str) -> dict[str, Any]:
        """What gets stored with the clip's framing."""
        return {
            "face_ratio": self.face_ratio,
            "follow": requested,
            "followed": self.follow,
            "speakers": self.speakers,
            "switches": len(self.switches),
        }


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
    follow: str = "speaker",
) -> TrackResult:
    tools = ffmpeg.detect(settings.bin_dir)
    proxy = Path(source["proxy_path"] or "")
    if not proxy.is_file():
        raise MediaError("The preview copy of this video is missing; re-import it")
    lo = max(0, start_ms - MARGIN_MS)
    hi = min(source["duration_ms"], end_ms + MARGIN_MS)

    width, height = video_size(tools.ffprobe.path, proxy)
    detector = FaceDetector(width, height)
    samples: list[tuple[int, list]] = []
    patches: dict[int, np.ndarray] = {}  # id(face) -> mouth patch
    for t, frame in sample_frames(tools.ffmpeg.path, proxy, width, height, lo, hi, cancel):
        faces = detector.detect(frame)
        if follow == "speaker" and len(faces) > 1:
            gray = frame.mean(axis=2)
            for face in faces:
                patch = mouth_patch(gray, face)
                if patch is not None:
                    patches[id(face)] = patch
        samples.append((t, faces))
    if not samples:
        raise MediaError("Could not read frames from this part of the video")
    # The last sample can fall just short of the range end; extend it so the path covers the clip.
    samples[-1] = (max(samples[-1][0], hi), samples[-1][1])

    cuts = cached_scene_cuts(tools.ffmpeg.path, proxy, work_dir, source["duration_ms"], cancel)
    crop = default_crop(aspect, source["width"], source["height"])

    if follow == "speaker":
        tracked = assign_tracks(samples)
        counts: dict[int, int] = {}
        for _, faces in tracked:
            for tid in faces:
                counts[tid] = counts.get(tid, 0) + 1
        regulars = [tid for tid, n in counts.items() if n >= len(tracked) * MIN_TRACK_SHARE]
        if len(regulars) >= 2:
            speech = _speech_flags(tools.ffmpeg.path, proxy, source, [t for t, _ in samples])
            result = pick_speaker(tracked, _mouth_activity(tracked, patches), speech)
            # A cut to another speaker is a hard cut, like a scene change.
            keyframes, face_ratio = camera_path(result.subject, sorted(set(cuts) | set(result.switches)), crop)
            return TrackResult(
                keyframes=[k.as_dict() for k in keyframes],
                face_ratio=round(face_ratio, 3),
                follow="speaker",
                speakers=result.speakers,
                switches=result.switches,
            )

    keyframes, face_ratio = camera_path(choose_subject(samples), cuts, crop)
    return TrackResult(keyframes=[k.as_dict() for k in keyframes], face_ratio=round(face_ratio, 3), speakers=int(face_ratio > 0))


def _mouth_activity(tracked: list[tuple[int, dict]], patches: dict[int, np.ndarray]) -> dict[tuple[int, int], float]:
    """How much each person's mouth changed since the previous sample (mean pixel difference)."""
    activity: dict[tuple[int, int], float] = {}
    previous: dict[int, np.ndarray] = {}
    for t, faces in tracked:
        current: dict[int, np.ndarray] = {}
        for tid, face in faces.items():
            patch = patches.get(id(face))
            if patch is None:
                continue
            current[tid] = patch
            if tid in previous:
                activity[(t, tid)] = float(np.abs(patch - previous[tid]).mean())
        previous = current
    return activity


def _speech_flags(ffmpeg_path: str, proxy: Path, source: Any, times: list[int]) -> list[bool]:
    """Whether there's sound at each sample time (talking, not silence)."""
    if not source["has_audio"]:
        return [True] * len(times)
    levels = loudness(ffmpeg_path, proxy, source["duration_ms"], True)
    threshold = silence_threshold(levels)
    flags = []
    for t in times:
        i = min(len(levels) - 1, max(0, int(t / 1000 * LOUDNESS_PER_SECOND)))
        flags.append(bool(levels[i] >= threshold))
    return flags
