import json
import statistics
import subprocess
from dataclasses import dataclass, replace
from fractions import Fraction
from pathlib import Path

from ..ffmpeg import NO_WINDOW
from . import MediaError

# r_frame_rate vs avg_frame_rate differing by more than this means the frame timing is uneven.
VFR_TOLERANCE = 0.01
# Headers can hide it (Matroska states one "default" rate for both), so the actual frame times are
# sampled too: all of a short video, else a few windows spread over it.
SAMPLE_ALL_BELOW_S = 60
SAMPLE_WINDOWS = 8
SAMPLE_WINDOW_S = 3
UNEVEN_SHARE = 0.02  # this share of frames may be off the usual spacing (a dropped frame here and there)

STANDARD_RATES = [Fraction(r) for r in ("24000/1001", "24", "25", "30000/1001", "30", "50", "60000/1001", "60")]


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
    # How long after the file's own start the first video frame comes (audio often starts slightly earlier).
    video_offset_s: float = 0.0
    color_transfer: str | None = None
    container: str = ""  # FFmpeg's format name, e.g. "mov,mp4,m4a,3gp,3g2,mj2" or "mpegts"
    start_s: float = 0.0  # the file's own first timestamp; MPEG-TS rarely starts at 0


def _rate(value: str | None) -> Fraction | None:
    try:
        rate = Fraction(value) if value else None
    except (ValueError, ZeroDivisionError):
        return None
    return rate if rate and rate > 0 else None


def grid_rate(average: Fraction, stated: Fraction | None, is_vfr: bool) -> Fraction:
    """The constant rate to edit and export at. Constant: the video's own, exactly (59.9401 means
    60000/1001). Variable: its full speed when it runs at that most of the time, else 30 or 60."""
    if is_vfr and stated in STANDARD_RATES and average >= stated * Fraction(55, 100):
        return stated
    nearest = min(STANDARD_RATES, key=lambda rate: abs(average / rate - 1))
    if abs(average / nearest - 1) < Fraction(1, 2000):
        return nearest
    if not is_vfr:
        return average
    return Fraction(30) if average <= 45 else Fraction(60)


def uneven_timing(times: list[float]) -> bool:
    """Whether frames come at uneven intervals, from a sample of their times (seconds)."""
    ordered = sorted(set(times))
    # A second or more between frames is the gap between two sampled windows.
    steps = [b - a for a, b in zip(ordered, ordered[1:]) if b - a < 1]
    if len(steps) < 10:
        return False
    usual = statistics.median(steps)
    # Formats that store whole milliseconds jitter by one.
    tolerance = max(0.0015, usual * 0.1)
    return sum(abs(s - usual) > tolerance for s in steps) > len(steps) * UNEVEN_SHARE


def _seconds(value: str | None) -> float | None:
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None


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

    rate = grid_rate(rate, real, is_vfr)

    duration = (data.get("format") or {}).get("duration") or video.get("duration")
    if not duration:
        raise MediaError("Could not determine the video duration")

    width, height = int(video["width"]), int(video["height"])
    # Phone footage is often stored landscape with a rotation flag; report the size as displayed.
    if _rotation(video) in (90, 270):
        width, height = height, width

    size = (data.get("format") or {}).get("size")
    video_start, file_start = _seconds(video.get("start_time")), _seconds((data.get("format") or {}).get("start_time"))
    video_offset = video_start - file_start if video_start is not None and file_start is not None else 0.0
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
        video_offset_s=video_offset,
        color_transfer=video.get("color_transfer"),
        container=(data.get("format") or {}).get("format_name") or "",
        start_s=file_start or 0.0,
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
    data = json.loads(result.stdout)
    info = parse_probe(data)
    if not info.is_vfr and uneven_timing(_sample_frame_times(ffprobe, path, info.duration_ms / 1000, data)):
        info = replace(info, is_vfr=True)
    return info


def _sample_frame_times(ffprobe: str, path: Path, duration_s: float, data: dict) -> list[float]:
    """Presentation times of some video frames. Reads packets only (nothing is decoded); empty on failure."""
    intervals: list[str] = []
    if duration_s > SAMPLE_ALL_BELOW_S:
        origin = _seconds((data.get("format") or {}).get("start_time")) or 0.0
        starts = [origin + duration_s * i / SAMPLE_WINDOWS for i in range(SAMPLE_WINDOWS)]
        intervals = ["-read_intervals", ",".join(f"{s:.3f}%+{SAMPLE_WINDOW_S}" for s in starts)]
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0", *intervals, "-show_entries", "packet=pts_time", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60, creationflags=NO_WINDOW,
        )  # fmt: skip
    except (OSError, subprocess.SubprocessError):
        return []
    times = (_seconds(line.strip().rstrip(",")) for line in result.stdout.splitlines())
    return [t for t in times if t is not None]


# Formats with an index, where a seek lands on the keyframe before the wanted time.
INDEXED_FORMATS = ("mov", "matroska", "webm")
PREROLL_S = 1.0  # decode at least this much before a cut


def preroll_for(ffprobe: str, path: Path, info: MediaInfo, start_ms: int) -> float:
    """How long before `start_ms` (ms) a render should start reading so that frame is decoded.

    Formats without an index (MPEG-TS above all) are entered at about the wanted time, and everything
    up to the next keyframe is lost; so reading must start before the last keyframe ahead of the cut.
    """
    if any(name in INDEXED_FORMATS for name in info.container.split(",")):
        return PREROLL_S
    start_s = start_ms / 1000
    for back in (15, 60, 240):
        begin = max(0.0, start_s - back)
        keyframes = [t for t in _keyframe_times(ffprobe, path, info.start_s + begin, info.start_s + start_s) if t <= info.start_s + start_s - 0.1]
        if keyframes:
            return max(PREROLL_S, start_s - (max(keyframes) - info.start_s) + 0.5)
        if begin == 0:
            break
    return start_s  # none found: read from the beginning


def _keyframe_times(ffprobe: str, path: Path, begin: float, end: float) -> list[float]:
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-select_streams", "v:0", "-read_intervals", f"{begin:.3f}%{end:.3f}",
             "-show_entries", "packet=pts_time,flags", "-of", "json", str(path)],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120, creationflags=NO_WINDOW,
        )  # fmt: skip
        packets = json.loads(result.stdout or "{}").get("packets", [])
    except (OSError, ValueError, subprocess.SubprocessError):
        return []
    times = (_seconds(p.get("pts_time")) for p in packets if "K" in p.get("flags", ""))
    return [t for t in times if t is not None]
