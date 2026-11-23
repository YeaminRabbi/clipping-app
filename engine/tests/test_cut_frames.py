"""Cuts contain exactly the right frames: none repeated, none dropped, none from next door.

Every frame of the source carries its own number as a gray level, so an export can be read back.
"""

import subprocess
from fractions import Fraction
from pathlib import Path

import numpy as np
import pytest

from app.media import CancelToken
from app.media.probe import preroll_for, probe
from app.media.render import build_video_filter, render_clip
from app.media.transcode import make_proxy
from conftest import FFMPEG, FFPROBE, needs_ffmpeg
from sync_media import av_offsets_ms, flash_beep

LEVELS = 30  # frame n is gray level (n % 30) * 8
RATES = ["30", "30000/1001", "60", "60000/1001"]
X264 = ["-c:v", "libx264", "-preset", "veryfast", "-qp", "8"]
VP9 = ["-c:v", "libvpx-vp9", "-crf", "10", "-b:v", "0", "-cpu-used", "8", "-deadline", "realtime"]


def numbered(path: Path, rate: str, seconds: int = 14, audio: bool = True, gop: int = 120) -> Path:
    webm = path.suffix == ".webm"
    sound = ["-f", "lavfi", "-i", f"sine=440:d={seconds}"] if audio else []
    codec = ["-c:a", "libopus" if webm else "aac"] if audio else []
    subprocess.run(
        [FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i",
         f"color=black:s=64x64:r={rate}:d={seconds},format=gray,geq=lum='mod(N,{LEVELS})*8'", *sound,
         "-pix_fmt", "yuv420p", *(VP9 if webm else X264), "-g", str(gop), *codec, str(path)],
        check=True, capture_output=True,
    )  # fmt: skip
    return path


def read_numbers(path: Path) -> np.ndarray:
    raw = subprocess.run(
        [FFMPEG, "-v", "error", "-i", str(path), "-vf", "scale=64:64", "-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "gray", "-"],
        capture_output=True, check=True,
    ).stdout  # fmt: skip
    frames = np.frombuffer(raw, np.uint8).reshape(-1, 64, 64)[:, 20:44, 20:44]
    return np.rint(frames.mean(axis=(1, 2)) / 8).astype(int)


def render_args(src: Path, info, start_ms: int, end_ms: int) -> dict:
    return dict(
        start_ms=start_ms, end_ms=end_ms, source_fps=info.fps_rational, output_fps=info.fps_rational, has_audio=info.has_audio,
        video_filter=build_video_filter("manual", 64, 64, info.fps_rational, (64, 64, 0, 0), "yuv420p"),
        encoder="libx264", quality="high", cancel=CancelToken(), video_offset_s=info.video_offset_s,
        preroll_s=preroll_for(FFPROBE, src, info, start_ms),
    )  # fmt: skip


def cut(src: Path, dest: Path, start_frame: int, count: int):
    info = probe(FFPROBE, src)
    rate = Fraction(info.fps_rational)
    render_clip(FFMPEG, src, dest, **render_args(src, info, round(start_frame * 1000 / rate), round((start_frame + count) * 1000 / rate)))
    return info


def check_cuts(src: Path, tmp_path: Path, starts=(0, 1, 100, 152, 203, 331), count: int = 45):
    info = probe(FFPROBE, src)
    # Time 0 is the file's own start; when the sound starts a little before the picture, the picture's
    # first frame is that many frames in. The preview (proxy) and the editor count the same way.
    shift = round(info.video_offset_s * Fraction(info.fps_rational))
    for start in starts:
        out = tmp_path / "out.mp4"
        cut(src, out, start, count)
        got = read_numbers(out)
        want = np.maximum(np.arange(start, start + count) - shift, 0) % LEVELS
        assert len(got) == count, f"{src.name} at {start}: {len(got)} frames"
        repeated = int((np.diff(got) == 0).sum()) - int((np.diff(want) == 0).sum())
        assert repeated == 0, f"{src.name} at {start}: {repeated} repeated frames"
        assert (got == want).all(), f"{src.name} at {start}: {list(zip(got, want))[:8]}"


@needs_ffmpeg
@pytest.mark.parametrize("rate", RATES)
@pytest.mark.parametrize("ext", ["mp4", "mkv", "webm"])
def test_no_frame_is_repeated_or_dropped(tmp_path, ext, rate):
    check_cuts(numbered(tmp_path / f"src.{ext}", rate), tmp_path)


@needs_ffmpeg
@pytest.mark.parametrize("rate", RATES)
def test_transport_streams_are_cut_at_the_right_frame(tmp_path, rate):
    # Keyframes 4 s or more apart: a seek lands between them, and everything up to the next one is lost.
    check_cuts(numbered(tmp_path / "src.ts", rate, gop=240), tmp_path)


@needs_ffmpeg
@pytest.mark.parametrize("gop", [30, 1000])
def test_transport_streams_with_many_or_one_keyframe(tmp_path, gop):
    check_cuts(numbered(tmp_path / "src.ts", "30", gop=gop), tmp_path, starts=(0, 203, 331))


@needs_ffmpeg
def test_preroll_reaches_back_to_a_keyframe_only_where_seeking_needs_it(tmp_path):
    ts = numbered(tmp_path / "src.ts", "30", gop=120)
    info = probe(FFPROBE, ts)
    assert info.container == "mpegts" and info.start_s > 0.5
    assert 3.4 <= preroll_for(FFPROBE, ts, info, 11_000) <= 4.0  # the keyframe at 8 s, and a little
    mp4 = numbered(tmp_path / "src.mp4", "30", gop=120)
    assert preroll_for(FFPROBE, mp4, probe(FFPROBE, mp4), 11_000) == 1.0


@needs_ffmpeg
def test_no_frame_is_repeated_or_dropped_without_sound(tmp_path):
    check_cuts(numbered(tmp_path / "src.mkv", "60", audio=False), tmp_path)


@needs_ffmpeg
@pytest.mark.parametrize("ext", ["mp4", "mkv"])
def test_export_shows_the_frames_the_preview_shows(tmp_path, ext):
    src = numbered(tmp_path / f"src.{ext}", "60")
    proxy = tmp_path / "proxy.mp4"
    info = probe(FFPROBE, src)
    make_proxy(FFMPEG, src, proxy, info, CancelToken())
    shift = round(info.video_offset_s * Fraction(info.fps_rational))  # the proxy file starts at its first picture
    cut(src, tmp_path / "out.mp4", 203, 45)
    assert (read_numbers(tmp_path / "out.mp4") == read_numbers(proxy)[203 - shift : 248 - shift]).all()


@needs_ffmpeg
@pytest.mark.parametrize("name, vfr", [("a.mp4", False), ("a.mkv", False), ("vfr.mkv", True), ("vfr.mp4", True), ("a.ts", False)])
def test_plain_cuts_keep_sound_in_sync(tmp_path, name, vfr):
    src = flash_beep(tmp_path / name, vfr=vfr)
    info = probe(FFPROBE, src)
    for start in (2300, 2317, 6950):
        render_clip(FFMPEG, src, tmp_path / "out.mp4", **render_args(src, info, start, start + 10000))
        offsets = av_offsets_ms(tmp_path / "out.mp4")
        assert len(offsets) >= 9
        assert abs(sum(offsets) / len(offsets)) < 1000 / 60, offsets
        assert max(map(abs, offsets)) < 1000 / min(60, info.fps), offsets
