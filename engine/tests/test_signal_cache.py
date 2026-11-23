"""Scene cuts and loudness are saved next to the proxy, but only when they were really measured (F-18);
long videos are read in pieces (F-22)."""

import subprocess
import threading
import time
import tracemalloc

import numpy as np
import pytest

from app.analysis import signals
from app.analysis.transcribe import SAMPLE_RATE, decode_audio
from app.analysis.signals import LOUDNESS_FILE, SCENES_FILE, cached_loudness, cached_scene_cuts, loudness, scene_cuts
from app.media import CancelToken, Cancelled, MediaError
from conftest import FFMPEG, needs_ffmpeg
from sync_media import flash_beep


@needs_ffmpeg
def test_failures_are_errors_and_are_not_saved(tmp_path):
    broken = tmp_path / "proxy.mp4"
    broken.write_bytes(b"not a video")
    with pytest.raises(MediaError):
        cached_scene_cuts(FFMPEG, broken, tmp_path, 1000, CancelToken())
    with pytest.raises(MediaError):
        cached_loudness(FFMPEG, broken, tmp_path, 1000, True)
    assert [p.name for p in tmp_path.iterdir()] == ["proxy.mp4"]


@needs_ffmpeg
def test_results_are_saved_and_reused(tmp_path, monkeypatch):
    video = flash_beep(tmp_path / "v.mp4", seconds=4)
    cuts = cached_scene_cuts(FFMPEG, video, tmp_path, 4000, CancelToken())
    levels = cached_loudness(FFMPEG, video, tmp_path, 4000, True)
    assert levels.max() > -20 > levels.min() and not list(tmp_path.glob("*.partial"))
    monkeypatch.setattr(signals, "scene_cuts", lambda *a: pytest.fail("measured again"))
    monkeypatch.setattr(signals, "loudness", lambda *a: pytest.fail("measured again"))
    assert cached_scene_cuts(FFMPEG, video, tmp_path, 4000, CancelToken()) == cuts
    assert (cached_loudness(FFMPEG, video, tmp_path, 4000, True) == levels).all()


@pytest.mark.parametrize("content", [b"", b"half a fi"])
def test_damaged_files_are_measured_again(tmp_path, monkeypatch, content):
    (tmp_path / SCENES_FILE).write_bytes(content)
    (tmp_path / LOUDNESS_FILE).write_bytes(content)
    monkeypatch.setattr(signals, "scene_cuts", lambda *a: [5])
    monkeypatch.setattr(signals, "loudness", lambda *a: np.zeros(3))
    assert cached_scene_cuts("f", tmp_path / "p", tmp_path, 1, CancelToken()) == [5]
    assert len(cached_loudness("f", tmp_path / "p", tmp_path, 1, True)) == 3


def test_results_saved_by_older_versions_are_not_trusted(tmp_path, monkeypatch):
    (tmp_path / "scenes.json").write_text("[]")
    np.save(tmp_path / "loudness.npy", np.full(10, -90.0))
    monkeypatch.setattr(signals, "scene_cuts", lambda *a: [5])
    monkeypatch.setattr(signals, "loudness", lambda *a: np.zeros(3))
    assert cached_scene_cuts("f", tmp_path / "p", tmp_path, 1, CancelToken()) == [5]
    assert cached_loudness("f", tmp_path / "p", tmp_path, 1, True).max() == 0


def test_several_jobs_at_once_measure_once(tmp_path, monkeypatch):
    calls = []

    def slow(*args):
        calls.append(1)
        time.sleep(0.2)
        return [7]

    monkeypatch.setattr(signals, "scene_cuts", slow)
    results = []
    threads = [threading.Thread(target=lambda: results.append(cached_scene_cuts("f", tmp_path / "p", tmp_path, 1, CancelToken()))) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results == [[7]] * 4 and len(calls) == 1


@needs_ffmpeg
def test_a_silent_video_is_not_a_failure(tmp_path):
    assert loudness(FFMPEG, tmp_path / "none.mp4", 2000, False).max() == signals.SILENCE_FLOOR_DB
    assert scene_cuts(FFMPEG, flash_beep(tmp_path / "v.mp4", seconds=2), 2000, CancelToken()) is not None


# --- memory (F-22) -------------------------------------------------------------------------------


def reference_levels(path) -> np.ndarray:
    """The straightforward way, all at once."""
    raw = subprocess.run([FFMPEG, "-v", "error", "-i", str(path), "-ac", "1", "-ar", "8000", "-f", "s16le", "-"], capture_output=True, check=True).stdout
    x = np.frombuffer(raw, np.int16).astype(np.float64) / 32768
    x = x[: len(x) // 800 * 800].reshape(-1, 800)
    return np.maximum(20 * np.log10(np.maximum(np.sqrt((x**2).mean(axis=1)), 1e-9)), signals.SILENCE_FLOOR_DB)


@needs_ffmpeg
def test_loudness_read_in_pieces_is_the_same(tmp_path):
    video = flash_beep(tmp_path / "v.mp4", seconds=100)  # more than one piece
    assert np.allclose(loudness(FFMPEG, video, 100_000, True), reference_levels(video), atol=0.01)


@needs_ffmpeg
@pytest.mark.parametrize("stated_ms", [0, 20_000, 500_000])
def test_decoded_audio_is_complete_whatever_the_stated_duration(tmp_path, stated_ms):
    video = flash_beep(tmp_path / "v.mp4", seconds=20)
    raw = subprocess.run(
        [FFMPEG, "-v", "error", "-i", str(video), "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "f32le", "-"], capture_output=True, check=True
    ).stdout
    audio = decode_audio(FFMPEG, video, stated_ms, CancelToken())
    assert (audio == np.frombuffer(raw, np.float32)).all() and audio.dtype == np.float32


@needs_ffmpeg
def test_reading_sound_takes_little_more_memory_than_the_result(tmp_path):
    video = flash_beep(tmp_path / "v.mp4", seconds=100)

    def peak(fn) -> float:
        tracemalloc.start()
        fn()
        value = tracemalloc.get_traced_memory()[1]
        tracemalloc.stop()
        return value / 1e6

    audio_mb = 100 * SAMPLE_RATE * 4 / 1e6
    assert peak(lambda: decode_audio(FFMPEG, video, 100_000, CancelToken())) < audio_mb * 1.3
    assert peak(lambda: loudness(FFMPEG, video, 100_000, True)) < 8, "one minute at a time"


@needs_ffmpeg
def test_decoding_can_be_cancelled(tmp_path):
    token = CancelToken()
    token.cancel()
    video = flash_beep(tmp_path / "v.mp4", seconds=2)
    with pytest.raises(Cancelled):
        decode_audio(FFMPEG, video, 2000, token)
    with pytest.raises(Cancelled):
        loudness(FFMPEG, video, 2000, True, token)
