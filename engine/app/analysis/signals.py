"""Scene cuts and loudness, measured on the proxy (small and constant frame rate, so it's fast)."""

import io
import json
import re
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path

import numpy as np

from ..ffmpeg import NO_WINDOW
from ..media import CancelToken, Cancelled, MediaError

LOUDNESS_PER_SECOND = 10
SILENCE_FLOOR_DB = -90.0
MIN_SILENCE_MS = 300
SCENE_THRESHOLD = 10.0  # scdet score (0-100); 10 catches hard cuts without reacting to camera motion

# Version 2: files made before could hold the result of a run that had failed.
SCENES_FILE = "scenes.v2.json"
LOUDNESS_FILE = "loudness.v2.npy"

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _cache_lock(path: Path) -> threading.Lock:
    """One computation of a file at a time: several exports may need it at once."""
    with _locks_guard:
        return _locks.setdefault(str(path), threading.Lock())


def _save(path: Path, data: bytes) -> None:
    """Write the whole file or none of it."""
    tmp = path.with_name(f"{path.name}.partial")
    tmp.write_bytes(data)
    tmp.replace(path)


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
    try:
        while chunk := proc.stderr.read(4096):
            if cancel.cancelled:
                raise Cancelled()
            buffer += chunk
            *lines, buffer = re.split(r"[\r\n]", buffer)
            for line in lines:
                if m := _SCD_TIME.search(line):
                    cuts.append(round(float(m.group(1)) * 1000))
                elif on_progress and duration_ms and (t := _OUT_TIME.search(line)):
                    seconds = int(t.group(1)) * 3600 + int(t.group(2)) * 60 + float(t.group(3))
                    on_progress(min(1.0, seconds * 1000 / duration_ms))
    except BaseException:
        proc.kill()
        raise
    finally:
        proc.wait()
    if proc.returncode != 0:
        raise MediaError("Could not look for scene changes in this video")
    return sorted(set(c for c in cuts if 0 < c < duration_ms))


def cached_scene_cuts(
    ffmpeg: str,
    proxy: Path,
    work_dir: Path,
    duration_ms: int,
    cancel: CancelToken,
    on_progress: Callable[[float], None] | None = None,
) -> list[int]:
    """Scene cuts for a source, computed once and saved next to its proxy. A failure isn't saved."""
    path = work_dir / SCENES_FILE
    with _cache_lock(path):
        if path.is_file():
            try:
                return json.loads(path.read_text())
            except (OSError, ValueError):
                pass
        cuts = scene_cuts(ffmpeg, proxy, duration_ms, cancel, on_progress)
        _save(path, json.dumps(cuts).encode())
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
    if result.returncode != 0:
        # Not the same as silence, which would let Tighten cut everything.
        raise MediaError("Could not measure the sound of this video")
    samples = np.frombuffer(result.stdout[: len(result.stdout) // 2 * 2], dtype=np.int16).astype(np.float64) / 32768
    window = rate // LOUDNESS_PER_SECOND
    usable = len(samples) // window * window
    if usable == 0:
        return np.full(frames, SILENCE_FLOOR_DB)
    rms = np.sqrt(np.mean(samples[:usable].reshape(-1, window) ** 2, axis=1))
    db = np.maximum(20 * np.log10(np.maximum(rms, 1e-9)), SILENCE_FLOOR_DB)
    return db


def cached_loudness(ffmpeg: str, proxy: Path, work_dir: Path, duration_ms: int, has_audio: bool) -> np.ndarray:
    """loudness(), saved next to the proxy after the first time. A failure isn't saved."""
    path = work_dir / LOUDNESS_FILE
    with _cache_lock(path):
        if path.is_file():
            try:
                return np.load(path)
            except (OSError, ValueError, EOFError):
                pass
        levels = loudness(ffmpeg, proxy, duration_ms, has_audio)
        data = io.BytesIO()
        np.save(data, levels)
        _save(path, data.getvalue())
        return levels


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
