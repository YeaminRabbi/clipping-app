"""Scene cuts and loudness, measured on the proxy (small and constant frame rate, so it's fast)."""

import json
import re
import subprocess
from collections.abc import Callable
from pathlib import Path

import numpy as np

from ..ffmpeg import NO_WINDOW
from ..media import CancelToken, Cancelled

LOUDNESS_PER_SECOND = 10
SILENCE_FLOOR_DB = -90.0
MIN_SILENCE_MS = 300
SCENE_THRESHOLD = 10.0  # scdet score (0-100); 10 catches hard cuts without reacting to camera motion

_SCD_TIME = re.compile(r"lavfi\.scd\.time:\s*([\d.]+)")
_OUT_TIME = re.compile(r"time=(\d+):(\d+):([\d.]+)")


def scene_cuts(
    ffmpeg: str,
    proxy: Path,
    duration_ms: int,
    cancel: CancelToken,
    on_progress: Callable[[float], None] | None = None,
) -> list[int]:
    """Times (ms) of hard cuts."""
    proc = subprocess.Popen(
        [ffmpeg, "-hide_banner", "-nostdin", "-i", str(proxy), "-an",
         "-vf", f"scdet=threshold={SCENE_THRESHOLD}", "-f", "null", "-"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=NO_WINDOW,
    )  # fmt: skip
    cuts: list[int] = []
    assert proc.stderr is not None
    # FFmpeg ends progress lines with \r, so read raw chunks and split on either line ending.
    buffer = ""
    while chunk := proc.stderr.read(4096):
        if cancel.cancelled:
            proc.kill()
            raise Cancelled()
        buffer += chunk
        *lines, buffer = re.split(r"[\r\n]", buffer)
        for line in lines:
            if m := _SCD_TIME.search(line):
                cuts.append(round(float(m.group(1)) * 1000))
            elif on_progress and duration_ms and (t := _OUT_TIME.search(line)):
                seconds = int(t.group(1)) * 3600 + int(t.group(2)) * 60 + float(t.group(3))
                on_progress(min(1.0, seconds * 1000 / duration_ms))
    proc.wait()
    return sorted(set(c for c in cuts if 0 < c < duration_ms))


def cached_scene_cuts(
    ffmpeg: str,
    proxy: Path,
    work_dir: Path,
    duration_ms: int,
    cancel: CancelToken,
    on_progress: Callable[[float], None] | None = None,
) -> list[int]:
    """Scene cuts for a source, computed once and saved as scenes.json next to its proxy."""
    path = work_dir / "scenes.json"
    if path.is_file():
        try:
            return json.loads(path.read_text())
        except ValueError:
            pass
    cuts = scene_cuts(ffmpeg, proxy, duration_ms, cancel, on_progress)
    path.write_text(json.dumps(cuts))
    return cuts


def loudness(ffmpeg: str, proxy: Path, duration_ms: int, has_audio: bool) -> np.ndarray:
    """RMS level in dBFS for each 100 ms."""
    frames = max(1, int(duration_ms / 1000 * LOUDNESS_PER_SECOND))
    if not has_audio:
        return np.full(frames, SILENCE_FLOOR_DB)
    rate = 8000
    result = subprocess.run(
        [ffmpeg, "-v", "error", "-nostdin", "-i", str(proxy), "-vn", "-ac", "1", "-ar", str(rate), "-f", "s16le", "-"],
        capture_output=True,
        creationflags=NO_WINDOW,
    )
    samples = np.frombuffer(result.stdout[: len(result.stdout) // 2 * 2], dtype=np.int16).astype(np.float64) / 32768
    window = rate // LOUDNESS_PER_SECOND
    usable = len(samples) // window * window
    if usable == 0:
        return np.full(frames, SILENCE_FLOOR_DB)
    rms = np.sqrt(np.mean(samples[:usable].reshape(-1, window) ** 2, axis=1))
    db = np.maximum(20 * np.log10(np.maximum(rms, 1e-9)), SILENCE_FLOOR_DB)
    return db


def silence_threshold(db: np.ndarray) -> float:
    """Adapts to the recording's noise floor: a bit above its quietest moments, within sane limits."""
    if len(db) == 0:
        return -45.0
    return float(min(-30.0, max(-55.0, np.percentile(db, 5) + 10)))


def silences(db: np.ndarray) -> list[tuple[int, int]]:
    """(start_ms, end_ms) spans quieter than the silence threshold for at least MIN_SILENCE_MS."""
    threshold = silence_threshold(db)
    step = 1000 // LOUDNESS_PER_SECOND
    spans: list[tuple[int, int]] = []
    start = None
    for i, level in enumerate(np.append(db, 0.0)):  # sentinel closes a trailing span
        if level < threshold and start is None:
            start = i
        elif level >= threshold and start is not None:
            if (i - start) * step >= MIN_SILENCE_MS:
                spans.append((start * step, i * step))
            start = None
    return spans
