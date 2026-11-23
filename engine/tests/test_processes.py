"""Child processes never outlive the call that started them."""

import os
import subprocess
import sys
import time
from pathlib import Path

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


ENGINE = """
import subprocess, sys, time
sys.path.insert(0, {engine!r})
from app.processes import kill_children_with_us
assert kill_children_with_us()
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
print(child.pid, flush=True)
time.sleep(60)
"""


def is_running(pid: int) -> bool:
    import ctypes

    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return False
    code = ctypes.c_ulong()
    ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
    ctypes.windll.kernel32.CloseHandle(handle)
    return code.value == 259  # STILL_ACTIVE


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_children_end_with_an_engine_that_is_terminated():
    # The base interpreter, as in the packaged app: a venv's launcher has a process group of its own.
    python = sys._base_executable
    program = ENGINE.format(engine=str(Path(__file__).resolve().parent.parent))
    engine = subprocess.Popen([python, "-c", program], stdout=subprocess.PIPE, text=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    child = int(engine.stdout.readline())
    assert is_running(child)
    engine.kill()
    engine.wait()
    deadline = time.monotonic() + 5
    while is_running(child):
        assert time.monotonic() < deadline, "the child outlived the engine"
        time.sleep(0.05)
