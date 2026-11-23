import subprocess
import threading
from collections import deque
from collections.abc import Callable
from fractions import Fraction
from pathlib import Path

from ..ffmpeg import NO_WINDOW
from . import CancelToken, Cancelled, MediaError
from .probe import MediaInfo

PROXY_HEIGHT = 480
PROXY_MAX_FPS = 60


def run_ffmpeg(
    ffmpeg: str,
    args: list[str],
    duration_ms: int,
    cancel: CancelToken,
    on_progress: Callable[[float], None] | None = None,
    cwd: Path | None = None,
) -> None:
    """Run FFmpeg, reporting progress (0..1) from its -progress output and killing it on cancel."""
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-progress", "pipe:1", "-nostats", *args]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=NO_WINDOW,
        cwd=cwd,
    )

    # Drain stderr on a thread so a chatty FFmpeg can't fill the pipe and block.
    stderr_tail: deque[str] = deque(maxlen=20)
    drain = threading.Thread(target=lambda: stderr_tail.extend(proc.stderr), daemon=True)
    drain.start()

    # Polling the cancel token between progress lines is enough: FFmpeg reports about twice a second.
    watcher = threading.Thread(target=lambda: _kill_on_cancel(proc, cancel), daemon=True)
    watcher.start()

    assert proc.stdout is not None
    for line in proc.stdout:
        key, _, value = line.strip().partition("=")
        if key == "out_time_us" and on_progress and duration_ms > 0 and value.isdigit():
            on_progress(min(1.0, int(value) / 1000 / duration_ms))
    proc.wait()
    drain.join(timeout=2)

    if cancel.cancelled:
        raise Cancelled()
    if proc.returncode != 0:
        detail = next((l.strip() for l in reversed(stderr_tail) if l.strip()), "unknown error")
        raise MediaError(f"FFmpeg failed: {detail}")


def _kill_on_cancel(proc: subprocess.Popen, cancel: CancelToken) -> None:
    while proc.poll() is None:
        if cancel.cancelled:
            proc.kill()
            return
        threading.Event().wait(0.2)


def proxy_fps(info: MediaInfo) -> str:
    """Constant frame rate for the proxy: the source's average rate, capped so proxies stay light."""
    rate = Fraction(info.fps_rational)
    return str(PROXY_MAX_FPS) if rate > PROXY_MAX_FPS else info.fps_rational


def make_proxy(
    ffmpeg: str,
    src: Path,
    dest: Path,
    info: MediaInfo,
    cancel: CancelToken,
    on_progress: Callable[[float], None] | None = None,
) -> None:
    """Low-res, constant-frame-rate H.264 copy for smooth scrubbing and frame stepping in the editor.

    A keyframe every second keeps seeking fast. Constant frame rate means frame N in the player is
    frame N in the source, even when the original has variable timing.
    """
    fps = proxy_fps(info)
    gop = max(1, round(float(Fraction(fps))))
    tmp = dest.with_suffix(".partial.mp4")
    args = [
        "-i", str(src),
        "-map", "0:v:0", "-map", "0:a:0?",
        "-vf", f"scale=-2:'min({PROXY_HEIGHT},ih)',fps={fps}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "26", "-pix_fmt", "yuv420p",
        "-g", str(gop), "-keyint_min", str(gop), "-sc_threshold", "0",
        "-c:a", "aac", "-b:a", "96k", "-ac", "2",
        "-movflags", "+faststart",
        str(tmp),
    ]  # fmt: skip
    try:
        run_ffmpeg(ffmpeg, args, info.duration_ms, cancel, on_progress)
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)


def make_poster(ffmpeg: str, src: Path, dest: Path, info: MediaInfo, cancel: CancelToken) -> None:
    """Thumbnail from 10% in, which skips most black intro frames."""
    at = f"{info.duration_ms * 0.1 / 1000:.3f}"
    args = ["-ss", at, "-i", str(src), "-frames:v", "1", "-vf", "scale=-2:360", "-q:v", "4", str(dest)]
    run_ffmpeg(ffmpeg, args, 0, cancel)
