import json
import subprocess
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from ..ffmpeg import NO_WINDOW
from . import MediaError

# r_frame_rate vs avg_frame_rate differing by more than this means the frame timing is uneven.
VFR_TOLERANCE = 0.01


@dataclass
class MediaInfo:
    duration_ms: int
    width: int
    height: int
    fps: float
    fps_rational: str  # exact rate for FFmpeg, e.g. "30000/1001"
    is_vfr: bool
    video_codec: str | None
    audio_codec: str | None
    has_audio: bool
    size_bytes: int | None


def _rate(value: str | None) -> Fraction | None:
    try:
        rate = Fraction(value) if value else None
    except (ValueError, ZeroDivisionError):
        return None
    return rate if rate and rate > 0 else None


def _rotation(stream: dict) -> int:
    for side in stream.get("side_data_list") or []:
        if "rotation" in side:
            return int(float(side["rotation"])) % 360
    rotate = (stream.get("tags") or {}).get("rotate")
    return int(rotate) % 360 if rotate else 0


def parse_probe(data: dict) -> MediaInfo:
    """Turn ffprobe JSON into the fields we store. Split out from probe() so it can be tested."""
    streams = data.get("streams") or []
    # Cover art in audio files shows up as a video stream; skip it.
    video = next(
        (s for s in streams if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")),
        None,
    )
    if video is None:
        raise MediaError("No video stream found in this file")
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)

    avg = _rate(video.get("avg_frame_rate"))
    real = _rate(video.get("r_frame_rate"))
    rate = avg or real
    if rate is None:
        raise MediaError("Could not determine the video frame rate")
    is_vfr = bool(avg and real and abs(float(avg) - float(real)) / float(real) > VFR_TOLERANCE)

    duration = (data.get("format") or {}).get("duration") or video.get("duration")
    if not duration:
        raise MediaError("Could not determine the video duration")

    width, height = int(video["width"]), int(video["height"])
    # Phone footage is often stored landscape with a rotation flag; report the size as displayed.
    if _rotation(video) in (90, 270):
        width, height = height, width

    size = (data.get("format") or {}).get("size")
    return MediaInfo(
        duration_ms=round(float(duration) * 1000),
        width=width,
        height=height,
        fps=round(float(rate), 3),
        fps_rational=f"{rate.numerator}/{rate.denominator}",
        is_vfr=is_vfr,
        video_codec=video.get("codec_name"),
        audio_codec=audio.get("codec_name") if audio else None,
        has_audio=audio is not None,
        size_bytes=int(size) if size else None,
    )


def probe(ffprobe: str, path: Path) -> MediaInfo:
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            creationflags=NO_WINDOW,
        )
    except subprocess.TimeoutExpired as err:
        raise MediaError("Reading the video's details timed out") from err
    if result.returncode != 0:
        detail = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "unknown error"
        raise MediaError(f"Not a readable video file ({detail})")
    return parse_probe(json.loads(result.stdout))
