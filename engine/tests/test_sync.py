"""Picture and sound must stay together through exports, whatever the source's frame timing."""

import pytest

from app.media import CancelToken
from app.media.probe import probe
from app.media.render import build_video_filter, render_clip
from conftest import FFMPEG, FFPROBE, needs_ffmpeg
from sync_media import av_offsets_ms, flash_beep


def render(src, dest, start_ms, end_ms, segments=None):
    info = probe(FFPROBE, src)
    render_clip(
        FFMPEG, src, dest, start_ms=start_ms, end_ms=end_ms, source_fps=info.fps_rational, output_fps=info.fps_rational,
        has_audio=info.has_audio, video_filter=build_video_filter("manual", 64, 64, info.fps_rational, (64, 64, 0, 0), "yuv420p"),
        encoder="libx264", quality="high", cancel=CancelToken(), segments=segments,
    )  # fmt: skip
    return info


@needs_ffmpeg
@pytest.mark.parametrize("name, codec", [("aac.mp4", "aac"), ("flac.mkv", "flac")])
def test_many_cuts_dont_add_up_to_drift(tmp_path, name, codec):
    src = flash_beep(tmp_path / name, seconds=40, audio_codec=codec)
    # 36 cuts of 300-400 ms in the dark, silent part of each second.
    edges = [(1000 * i + 400 + 17 * (i % 7), 1000 * i + 700 + 17 * (i % 5)) for i in range(1, 37)]
    segments = [(500, edges[0][0]), *[(a[1], b[0]) for a, b in zip(edges, edges[1:])], (edges[-1][1], 38000)]
    info = render(src, tmp_path / "out.mp4", 500, 38000, segments)
    offsets = av_offsets_ms(tmp_path / "out.mp4")
    assert len(offsets) >= 30
    assert max(map(abs, offsets)) < 1000 / info.fps, [round(float(o), 1) for o in offsets]
