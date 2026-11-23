import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.config import PROJECT_ROOT, Settings  # noqa: E402
from app.ffmpeg import detect  # noqa: E402
from app.main import create_app  # noqa: E402

TOKEN = "test-token"
BIN_DIR = PROJECT_ROOT / "bin"
_tools = detect(BIN_DIR)
FFMPEG = _tools.ffmpeg.path
FFPROBE = _tools.ffprobe.path

needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="FFmpeg not available")
needs_tts = pytest.mark.skipif(sys.platform != "win32", reason="needs Windows text-to-speech")

HERE = Path(__file__).parent
# Speech models downloaded by the tests, shared between runs.
MODELS_DIR = PROJECT_ROOT / ".cache" / "models"
SCENE_CUTS_S = (15, 30, 45)


def make_video(path: Path, seconds: int, size: str = "1280x720", rate: int = 30) -> Path:
    subprocess.run(
        [FFMPEG, "-y", "-v", "error",
         "-f", "lavfi", "-i", f"testsrc2=size={size}:rate={rate}:duration={seconds}",
         "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
         "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(path)],
        check=True,
    )  # fmt: skip
    return path


def wait_for(client, source_id: int, statuses: set[str], timeout: float = 60) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        source = client.get(f"/sources/{source_id}").json()
        if source["status"] in statuses:
            return source
        time.sleep(0.1)
    raise AssertionError(f"source {source_id} stuck in {source['status']}")


@pytest.fixture(scope="session")
def short_video(tmp_path_factory) -> Path:
    return make_video(tmp_path_factory.mktemp("media") / "sample clip.mp4", 3)


@pytest.fixture
def client(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", token=TOKEN, bin_dir=BIN_DIR)
    settings.projects_dir.mkdir(parents=True)
    with TestClient(create_app(settings), headers={"x-engine-token": TOKEN}) as c:
        yield c


@pytest.fixture
def project(client) -> dict:
    return client.post("/projects", json={"name": "Test"}).json()


@pytest.fixture(scope="session")
def podcast(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("podcast")
    wav = d / "speech.wav"
    subprocess.run(
        ["powershell", "-NoProfile", "-File", str(HERE / "make_speech.ps1"), "-Out", str(wav),
         "-TextFile", str(HERE / "fixtures" / "podcast.txt")],
        check=True, capture_output=True,
    )  # fmt: skip
    # Scene detection compares brightness, so neighbouring scenes must differ in brightness.
    colors = ["red", "white", "blue", "yellow"]
    inputs = []
    for c in colors:
        inputs += ["-f", "lavfi", "-i", f"color={c}:s=640x360:r=30:d=15"]
    video = d / "podcast.mp4"
    subprocess.run(
        [FFMPEG, "-y", "-v", "error", *inputs, "-i", str(wav),
         "-filter_complex", "[0:v][1:v][2:v][3:v]concat=n=4:v=1[v]", "-map", "[v]", "-map", "4:a",
         "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(video)],
        check=True,
    )  # fmt: skip
    return video
