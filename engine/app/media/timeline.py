"""Assets for the editor timeline: a thumbnail sprite sheet and an audio waveform."""

import math
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

from ..ffmpeg import NO_WINDOW
from . import CancelToken, Cancelled, MediaError
from .transcode import run_ffmpeg

THUMB_HEIGHT = 90
MAX_THUMBS = 300
MAX_SPRITE_WIDTH = 4096
PEAKS_PER_SECOND = 100
WAVEFORM_SAMPLE_RATE = 8000


@dataclass
class ThumbLayout:
    interval_s: float
    count: int
    cols: int
    rows: int
    tile_w: int
    tile_h: int

    def as_dict(self) -> dict:
        return asdict(self)


def thumb_layout(duration_ms: int, width: int, height: int) -> ThumbLayout:
    """Deterministic sprite layout, so the client knows it without a separate metadata file."""
    duration_s = max(duration_ms / 1000, 0.001)
    interval = max(1.0, duration_s / MAX_THUMBS)
    count = max(1, math.ceil(duration_s / interval))
    tile_w = max(2, round(THUMB_HEIGHT * width / height / 2) * 2)
    cols = max(1, min(count, MAX_SPRITE_WIDTH // tile_w))
    rows = math.ceil(count / cols)
    return ThumbLayout(interval_s=round(interval, 4), count=count, cols=cols, rows=rows, tile_w=tile_w, tile_h=THUMB_HEIGHT)


def make_thumbs(ffmpeg: str, proxy: Path, dest: Path, layout: ThumbLayout, duration_ms: int, cancel: CancelToken) -> None:
    # The proxy has a keyframe every second and thumbnails are at least a second apart, so decoding
    # keyframes only is enough and much faster.
    tmp = dest.with_suffix(".partial.jpg")
    # Thumbnail n is the first keyframe at or after n * interval, matching how the client maps time to
    # tiles. (The fps filter drops the last few frames on a keyframe-only stream.)
    vf = (
        f"select='gte(t\\,selected_n*{layout.interval_s}-0.01)',"
        f"scale={layout.tile_w}:{layout.tile_h}:force_original_aspect_ratio=decrease,"
        f"pad={layout.tile_w}:{layout.tile_h}:(ow-iw)/2:(oh-ih)/2,tile={layout.cols}x{layout.rows}"
    )
    args = ["-skip_frame", "nokey", "-i", str(proxy), "-an", "-vf", vf, "-frames:v", "1", "-q:v", "5", str(tmp)]
    try:
        run_ffmpeg(ffmpeg, args, duration_ms, cancel)
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)


def make_waveform(ffmpeg: str, proxy: Path, dest: Path, cancel: CancelToken) -> None:
    """Write PEAKS_PER_SECOND peak levels per second as bytes (0-255, scaled to the loudest moment)."""
    proc = subprocess.Popen(
        [ffmpeg, "-hide_banner", "-nostdin", "-v", "error", "-i", str(proxy), "-vn",
         "-ac", "1", "-ar", str(WAVEFORM_SAMPLE_RATE), "-f", "s16le", "-"],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        creationflags=NO_WINDOW,
    )  # fmt: skip
    bucket = WAVEFORM_SAMPLE_RATE // PEAKS_PER_SECOND
    peaks: list[np.ndarray] = []
    leftover = np.empty(0, dtype=np.int16)
    assert proc.stdout is not None
    try:
        while chunk := proc.stdout.read(WAVEFORM_SAMPLE_RATE * 2 * 30):  # 30 s at a time
            if cancel.cancelled:
                proc.kill()
                raise Cancelled()
            samples = np.concatenate([leftover, np.frombuffer(chunk[: len(chunk) // 2 * 2], dtype=np.int16)])
            usable = len(samples) // bucket * bucket
            if usable:
                peaks.append(np.abs(samples[:usable].astype(np.int32)).reshape(-1, bucket).max(axis=1))
            leftover = samples[usable:]
        if len(leftover):
            peaks.append(np.array([np.abs(leftover.astype(np.int32)).max()]))
    finally:
        proc.wait()
    if proc.returncode not in (0, None) and not peaks:
        raise MediaError("Could not read the audio track")

    levels = np.concatenate(peaks) if peaks else np.zeros(0, dtype=np.int32)
    loudest = levels.max() if len(levels) else 0
    scaled = (levels * 255 / loudest).astype(np.uint8) if loudest else levels.astype(np.uint8)
    tmp = dest.with_suffix(".partial")
    tmp.write_bytes(scaled.tobytes())
    tmp.replace(dest)
