"""Child processes never outlive the call that started them."""

import subprocess
import sys
import time

import pytest

from app.analysis.signals import scene_cuts
from app.media import CancelToken
from app.media import timeline
from app.media.timeline import make_waveform
from app.media.transcode import run_ffmpeg

TALKS = """
import sys, time
for i in range(200):
    print('out_time_us=%d' % (i * 1000), flush=True)
    print('frame=1 time=00:00:%05.2f' % (i / 10), file=sys.stderr, flush=True)
    time.sleep(0.05)
"""
FLOODS = "import sys\nwhile True: sys.stdout.buffer.write(b'x' * 65536)"


@pytest.fixture
def started(monkeypatch):
    """Runs a small Python program instead of FFmpeg; the list collects the processes."""
    real, processes = subprocess.Popen, []

    def use(program: str):
        def popen(cmd, **kwargs):
            processes.append(real([sys.executable, "-c", program], **kwargs))
            return processes[-1]

        monkeypatch.setattr(subprocess, "Popen", popen)
        return processes

    return use


def boom(_fraction: float) -> None:
    raise RuntimeError("could not save progress")


def test_ffmpeg_is_stopped_when_reporting_progress_fails(started):
    processes = started(TALKS)
    with pytest.raises(RuntimeError, match="could not save progress"):
        run_ffmpeg("ffmpeg", [], 1000, CancelToken(), boom)
    assert processes[0].poll() is not None


def test_scene_detection_is_stopped_when_reporting_progress_fails(started, tmp_path):
    processes = started(TALKS)
    with pytest.raises(RuntimeError):
        scene_cuts("ffmpeg", tmp_path / "p.mp4", 1000, CancelToken(), boom)
    assert processes[0].poll() is not None


def test_waveform_is_stopped_when_it_fails(started, tmp_path, monkeypatch):
    processes = started(FLOODS)
    monkeypatch.setattr(timeline.np, "concatenate", lambda parts: (_ for _ in ()).throw(MemoryError()))
    begun = time.monotonic()
    with pytest.raises(MemoryError):
        make_waveform("ffmpeg", tmp_path / "p.mp4", tmp_path / "w.bin", CancelToken())
    assert processes[0].poll() is not None and time.monotonic() - begun < 10


def test_a_busy_database_does_not_fail_a_job(client, monkeypatch):
    import sqlite3

    ingest = client.app.state.ingest

    def busy(*args, **kwargs):
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(ingest, "_update", busy)
    ingest._progress_reporter(1, CancelToken(), 0, 1)(0.5)  # must not raise
