"""Rendering a clip from the original source: frame-accurate trim, framing and encoding."""

import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from ..ffmpeg import HW_ENCODERS, NO_WINDOW
from . import CancelToken
from .transcode import run_ffmpeg

QUALITY_LEVELS = ("high", "balanced", "small")

# Per encoder: the quality option and its value for high / balanced / small.
_QUALITY_ARGS: dict[str, tuple[list[str], tuple[int, int, int]]] = {
    "libx264": (["-preset", "medium", "-crf"], (18, 21, 26)),
    "libx265": (["-preset", "medium", "-crf"], (21, 25, 30)),
    "h264_nvenc": (["-preset", "p5", "-tune", "hq", "-rc", "vbr", "-b:v", "0", "-cq"], (19, 23, 28)),
    "hevc_nvenc": (["-preset", "p5", "-tune", "hq", "-rc", "vbr", "-b:v", "0", "-cq"], (21, 25, 30)),
    "h264_qsv": (["-preset", "medium", "-global_quality"], (20, 24, 29)),
    "hevc_qsv": (["-preset", "medium", "-global_quality"], (22, 26, 31)),
    "h264_amf": (["-quality", "quality", "-rc", "cqp", "-qp_i", "{q}", "-qp_p", "{q}", "-qp_b"], (20, 24, 29)),
    "hevc_amf": (["-quality", "quality", "-rc", "cqp", "-qp_i", "{q}", "-qp_p", "{q}", "-qp_b"], (22, 26, 31)),
    "h264_videotoolbox": (["-q:v"], (65, 55, 45)),
    "hevc_videotoolbox": (["-q:v"], (65, 55, 45)),
}

CPU_ENCODERS = {"h264": "libx264", "hevc": "libx265"}

_encoder_checks: dict[str, bool] = {}
_encoder_lock = threading.Lock()


def pixel_format(encoder: str) -> str:
    return "nv12" if encoder.endswith("_qsv") else "yuv420p"


def encoder_args(encoder: str, quality: str) -> list[str]:
    option, values = _QUALITY_ARGS[encoder]
    q = values[QUALITY_LEVELS.index(quality)]
    args = ["-c:v", encoder, *[a.replace("{q}", str(q)) for a in option], str(q)]
    if encoder.startswith("hevc") or encoder == "libx265":
        args += ["-tag:v", "hvc1"]  # lets Apple devices and QuickTime play HEVC in MP4
    return args


def encoder_works(ffmpeg: str, encoder: str) -> bool:
    """An encoder can be compiled in without the GPU or driver being present, so try a tiny encode."""
    with _encoder_lock:
        if encoder not in _encoder_checks:
            try:
                result = subprocess.run(
                    [ffmpeg, "-hide_banner", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=256x256:d=0.2",
                     "-vf", f"format={pixel_format(encoder)}", "-c:v", encoder, "-f", "null", "-"],
                    capture_output=True, timeout=30, creationflags=NO_WINDOW,
                )  # fmt: skip
                _encoder_checks[encoder] = result.returncode == 0
            except (OSError, subprocess.SubprocessError):
                _encoder_checks[encoder] = False
        return _encoder_checks[encoder]


def pick_encoder(ffmpeg: str, codec: str, allow_hardware: bool, compiled_hw: dict[str, list[str]]) -> str:
    if allow_hardware:
        for vendor in HW_ENCODERS:
            for name in compiled_hw.get(vendor, []):
                if name.startswith(codec) and encoder_works(ffmpeg, name):
                    return name
    return CPU_ENCODERS[codec]


@dataclass
class FitOptions:
    background: str = "blur"  # blur | black | white
    dim: float = 0.25  # darken the background by this much (0..0.6)
    zoom: float = 1.0  # scale the picture beyond "fit", trimming its edges (1.0..1.5)
    position: str = "center"  # center | top

    @classmethod
    def from_dict(cls, data: dict | None) -> "FitOptions":
        data = data or {}
        return cls(
            background=data.get("background") if data.get("background") in ("blur", "black", "white") else "blur",
            dim=min(0.6, max(0.0, float(data.get("dim", 0.25)))),
            zoom=min(1.5, max(1.0, float(data.get("zoom", 1.0)))),
            position="top" if data.get("position") == "top" else "center",
        )


@dataclass
class CropPath:
    """A moving crop: fixed size, position keyframed over time (seconds relative to the seek point)."""

    w: int
    h: int
    points: list[tuple[float, int, int]]  # (t, x, y) in source pixels


def piecewise_expr(points: list[tuple[float, float]]) -> str:
    """FFmpeg expression in `t` that interpolates linearly between (time, value) points.

    Written as a flat sum of time-gated segments rather than nested if()s, so long paths stay valid.
    """
    if len(points) == 1:
        return str(points[0][1])
    t0, v0 = points[0]
    terms = [f"lt(t,{t0:.4f})*{v0}"]
    for (ta, va), (tb, vb) in zip(points, points[1:]):
        if tb <= ta:
            continue
        slope = (vb - va) / (tb - ta)
        terms.append(f"gte(t,{ta:.4f})*lt(t,{tb:.4f})*({va}+{slope:.6f}*(t-{ta:.4f}))")
    tn, vn = points[-1]
    terms.append(f"gte(t,{tn:.4f})*{vn}")
    return "trunc(" + "+".join(terms) + ")"


def build_video_filter(
    mode: str,
    out_w: int,
    out_h: int,
    fps: str,
    crop_px: tuple[int, int, int, int] | None,
    pix_fmt: str,
    *,
    path: CropPath | None = None,
    fit: FitOptions | None = None,
    overlay: str = "",
) -> str:
    """Filter graph from the source's displayed frame to the output frame, at a constant frame rate."""
    # `overlay` (e.g. burned-in captions) is drawn on the finished frame, before the pixel format.
    tail = f"setsar=1,{overlay + ',' if overlay else ''}format={pix_fmt}"
    if mode == "fit":
        return _fit_filter(out_w, out_h, fps, tail, fit or FitOptions())
    if mode == "smart":
        assert path is not None
        x = piecewise_expr([(t, px) for t, px, _ in path.points])
        y = piecewise_expr([(t, py) for t, _, py in path.points])
        return f"[0:v]fps={fps},crop=w={path.w}:h={path.h}:x='{x}':y='{y}',scale={out_w}:{out_h}:flags=lanczos,{tail}[v]"
    assert crop_px is not None
    w, h, x, y = crop_px
    return f"[0:v]fps={fps},crop={w}:{h}:{x}:{y},scale={out_w}:{out_h}:flags=lanczos,{tail}[v]"


def _fit_filter(out_w: int, out_h: int, fps: str, tail: str, opt: FitOptions) -> str:
    """The whole picture (optionally zoomed) over a blurred copy of itself or a solid color."""
    box_w, box_h = round(out_w * opt.zoom / 2) * 2, round(out_h * opt.zoom / 2) * 2
    fg = (
        f"scale={box_w}:{box_h}:force_original_aspect_ratio=decrease,"
        f"crop='min(iw,{out_w})':'min(ih,{out_h})'"
    )
    y = "(H-h)/2" if opt.position == "center" else "(H-h)*0.15"
    if opt.background == "blur":
        # Blurring a quarter-size copy is much faster and gives a softer, smoother result.
        qw, qh = max(2, out_w // 4 // 2 * 2), max(2, out_h // 4 // 2 * 2)
        dim = f",lutyuv=y=val*{1 - opt.dim:.3f}" if opt.dim > 0 else ""
        return (
            f"[0:v]fps={fps},split=2[bgsrc][fgsrc];"
            f"[bgsrc]scale={qw}:{qh}:force_original_aspect_ratio=increase,crop={qw}:{qh},gblur=sigma=8,"
            f"scale={out_w}:{out_h}{dim}[bg];"
            f"[fgsrc]{fg}[fg];"
            f"[bg][fg]overlay=(W-w)/2:{y},{tail}[v]"
        )
    # The solid background is painted over a copy of the video rather than taken from a color
    # source, so it has the video's timestamps: a separate source starts at 0 while the trimmed
    # video starts half a frame later, which made the first frame background only.
    color = "black" if opt.background == "black" else "white"
    return (
        f"[0:v]fps={fps},split=2[bgsrc][fgsrc];"
        f"[bgsrc]scale={out_w}:{out_h},drawbox=x=0:y=0:w=iw:h=ih:color={color}:t=fill[bg];"
        f"[fgsrc]{fg}[fg];"
        f"[bg][fg]overlay=(W-w)/2:{y},{tail}[v]"
    )


def trim_window(start_ms: int, end_ms: int, fps: str) -> tuple[float, Fraction]:
    """(seek seconds, exact duration) that select exactly the frames from start to end.

    Times are snapped to frame numbers, then the seek point is put half a frame early so rounding in
    the stored milliseconds can never drop the first frame.
    """
    rate = Fraction(fps)
    start_frame = round(start_ms * rate / 1000)
    end_frame = max(start_frame + 1, round(end_ms * rate / 1000))
    seek = max(0.0, float((start_frame - Fraction(1, 2)) / rate))
    return seek, (end_frame - start_frame) / rate


def segment_select(segments: list[tuple[float, float]], fps: str, has_audio: bool) -> tuple[float, Fraction, str]:
    """(seek seconds, total duration, graph) keeping only the frames and audio inside `segments`.

    Uses select/aselect and renumbers timestamps, which streams through the source once instead of
    buffering every segment. Video picks frames by number (half-frame margins, as in trim_window);
    audio is cut at the exact frame times, so picture and sound stay in sync across every join.
    """
    rate = Fraction(fps)
    frames = [(round(a * rate / 1000), round(b * rate / 1000)) for a, b in segments]
    frames = [(fa, fb) for fa, fb in frames if fb > fa]
    seek = max(0.0, float((frames[0][0] - Fraction(1, 2)) / rate))
    video_terms, audio_terms = [], []
    for fa, fb in frames:
        va, vb = float((fa - Fraction(1, 2)) / rate) - seek, float((fb - Fraction(1, 2)) / rate) - seek
        aa, ab = float(fa / rate) - seek, float(fb / rate) - seek
        video_terms.append(f"between(t,{va:.6f},{vb - 1e-6:.6f})")
        audio_terms.append(f"between(t,{aa:.6f},{ab - 1e-6:.6f})")
    duration = sum((Fraction(fb - fa) / rate for fa, fb in frames), Fraction(0))
    graph = f"[0:v]select='{'+'.join(video_terms)}',setpts=N/({rate.numerator}/{rate.denominator})/TB[vsel]"
    if has_audio:
        graph += f";[0:a]aselect='{'+'.join(audio_terms)}',asetpts=N/SR/TB[asel]"
    return seek, duration, graph


def output_frame_count(duration: Fraction, output_fps: str) -> int:
    return max(1, round(duration * Fraction(output_fps)))


def render_clip(
    ffmpeg: str,
    src: Path,
    dest: Path,
    *,
    start_ms: int,
    end_ms: int,
    source_fps: str,
    output_fps: str,
    has_audio: bool,
    audio_gain: float,
    video_filter: str,
    work_dir: Path | None = None,
    encoder: str,
    quality: str,
    cancel: CancelToken,
    on_progress: Callable[[float], None] | None = None,
    segments: list[tuple[float, float]] | None = None,
) -> None:
    """Render [start_ms, end_ms], or only the kept `segments` inside it, played back to back.

    `video_filter` reads the source as [0:v]; for segments it's fed the joined frames instead.
    """
    seek, duration = trim_window(start_ms, end_ms, source_fps)
    audio_map = "0:a:0?"
    input_limit: list[str] = []
    if segments and len(segments) > 1:
        seek, duration, select_graph = segment_select(segments, source_fps, has_audio)
        video_filter = select_graph + ";" + video_filter.replace("[0:v]", "[vsel]")
        audio_map = "[asel]"
        # Stop reading the source at the end of the last segment.
        input_limit = ["-t", f"{segments[-1][1] / 1000 - seek + 0.2:.6f}"]
    if has_audio and abs(audio_gain - 1.0) > 1e-6:
        audio_input = "[asel]" if audio_map == "[asel]" else "[0:a:0]"
        # Above unity, a fast limiter prevents hard digital clipping. This protects the output but
        # cannot restore detail already lost in a quiet/noisy recording, so large boosts can still
        # make distortion and noise more noticeable.
        audio_filter = f"volume={max(0.0, min(2.0, audio_gain)):.4f}"
        if audio_gain > 1.0:
            audio_filter += ",alimiter=limit=0.95:attack=5:release=50:level=false"
        video_filter += f";{audio_input}{audio_filter}[aout]"
        audio_map = "[aout]"
    audio = ["-map", audio_map, "-c:a", "aac", "-b:a", "192k", "-ac", "2"] if has_audio else ["-an"]
    tmp = dest.with_name(dest.stem + ".partial" + dest.suffix)
    # The graph goes in a file: a moving crop's expression can exceed the command-line length limit.
    graph = dest.with_name(dest.stem + ".partial.graph.txt")
    graph.write_text(video_filter, encoding="utf-8")
    # An exact frame count for video: a printed duration is rounded and can let one extra frame in.
    # The duration still bounds the audio.
    args = [
        "-ss", f"{seek:.6f}", *input_limit, "-i", str(src), "-t", f"{float(duration):.6f}",
        "-/filter_complex", str(graph), "-map", "[v]", "-r", output_fps,
        "-frames:v", str(output_frame_count(duration, output_fps)),
        *encoder_args(encoder, quality),
        *audio,
        "-movflags", "+faststart",
        str(tmp),
    ]  # fmt: skip
    try:
        # work_dir holds files the graph refers to by relative name (captions, fonts).
        run_ffmpeg(ffmpeg, args, round(float(duration) * 1000), cancel, on_progress, cwd=work_dir)
        tmp.replace(dest)
    finally:
        tmp.unlink(missing_ok=True)
        graph.unlink(missing_ok=True)
