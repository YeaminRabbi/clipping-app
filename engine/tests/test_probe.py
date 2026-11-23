from fractions import Fraction

import pytest

from app.media import MediaError
from app.media.probe import grid_rate, parse_probe, probe, uneven_timing
from conftest import FFPROBE, needs_ffmpeg
from sync_media import flash_beep


def _probe(video: dict | None = None, audio: bool = True, duration: str = "12.5") -> dict:
    streams = []
    if video is not None:
        streams.append({"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080,
                        "avg_frame_rate": "30000/1001", "r_frame_rate": "30000/1001", **video})  # fmt: skip
    if audio:
        streams.append({"codec_type": "audio", "codec_name": "aac"})
    return {"streams": streams, "format": {"duration": duration, "size": "1000"}}


def test_basic_fields():
    info = parse_probe(_probe({}))
    assert (info.width, info.height, info.duration_ms) == (1920, 1080, 12500)
    assert info.fps == 29.97 and info.fps_rational == "30000/1001"
    assert info.has_audio and not info.is_vfr


def test_rotated_phone_video_reports_display_size():
    info = parse_probe(_probe({"side_data_list": [{"rotation": -90}]}))
    assert (info.width, info.height) == (1080, 1920)


def test_legacy_rotate_tag():
    info = parse_probe(_probe({"tags": {"rotate": "90"}}))
    assert (info.width, info.height) == (1080, 1920)


def test_variable_frame_rate_detected():
    info = parse_probe(_probe({"avg_frame_rate": "2997/100", "r_frame_rate": "60/1"}))
    assert info.is_vfr


def test_cover_art_is_not_a_video():
    with pytest.raises(MediaError, match="No video stream"):
        parse_probe(_probe({"disposition": {"attached_pic": 1}}))


def test_audio_only_rejected():
    with pytest.raises(MediaError):
        parse_probe(_probe(None))


def test_no_audio():
    assert not parse_probe(_probe({}, audio=False)).has_audio


@needs_ffmpeg
@pytest.mark.parametrize("ext", ["mkv", "mp4"])
def test_variable_frame_rate_is_detected_in_real_files(tmp_path, ext):
    # Matroska states the same rate twice, so this can only be seen in the frames themselves.
    assert probe(FFPROBE, flash_beep(tmp_path / f"v.{ext}", vfr=True)).is_vfr
    assert not probe(FFPROBE, flash_beep(tmp_path / f"c.{ext}")).is_vfr


@needs_ffmpeg
def test_variable_frame_rate_is_detected_when_only_parts_of_a_long_video_are_read(tmp_path, monkeypatch):
    monkeypatch.setattr("app.media.probe.SAMPLE_ALL_BELOW_S", 10)
    assert probe(FFPROBE, flash_beep(tmp_path / "v.mkv", seconds=44, vfr=True)).is_vfr
    assert not probe(FFPROBE, flash_beep(tmp_path / "c.mkv", seconds=44)).is_vfr


def test_uneven_timing():
    milliseconds = [round(i * 1000 / 60) / 1000 for i in range(600)]
    assert not uneven_timing(milliseconds), "whole-millisecond rounding is not uneven"
    assert not uneven_timing([t for i, t in enumerate(milliseconds) if i % 200 != 7]), "a few dropped frames aren't either"
    assert uneven_timing(milliseconds[:300] + [5 + i / 15 for i in range(1, 60)])
    assert not uneven_timing([0, 0.1, 0.3])


@pytest.mark.parametrize(
    "average, stated, vfr, expected",
    [
        ("19001/317", "19001/317", False, "60000/1001"),  # how Matroska reports 59.94
        ("30000/1001", "30000/1001", False, "30000/1001"),
        ("15", "15", False, "15"),  # unusual but constant: kept
        ("75/2", "60", True, "60"),  # mostly full speed
        ("2997/100", "60", True, "30000/1001"),
        ("27", "90000", True, "30"),
        ("52", "1000", True, "60"),
    ],
)
def test_grid_rate(average, stated, vfr, expected):
    assert grid_rate(Fraction(average), Fraction(stated), vfr) == Fraction(expected)
