import pytest

from app.media import MediaError
from app.media.probe import parse_probe


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
