"""Scene cuts and loudness are saved next to the proxy, but only when they were really measured (F-18)."""

import threading
import time

import numpy as np
import pytest

from app.analysis import signals
from app.analysis.signals import LOUDNESS_FILE, SCENES_FILE, cached_loudness, cached_scene_cuts, loudness, scene_cuts
from app.media import CancelToken, MediaError
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
