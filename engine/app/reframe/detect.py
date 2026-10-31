"""Sampling frames from the proxy and detecting faces in them (OpenCV YuNet)."""

import json
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..config import ENGINE_DIR
from ..ffmpeg import NO_WINDOW
from ..media import CancelToken, Cancelled, MediaError

MODEL_PATH = ENGINE_DIR / "models" / "face_detection_yunet_2023mar.onnx"
SAMPLE_FPS = 5
SCORE_THRESHOLD = 0.6
NMS_THRESHOLD = 0.3


@dataclass
class Face:
    """A face box normalized to the frame (0..1)."""

    x: float
    y: float
    w: float
    h: float
    score: float

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    @property
    def area(self) -> float:
        return self.w * self.h


class FaceDetector:
    def __init__(self, width: int, height: int):
        import cv2

        # Errors only: OpenCV 5 warns about backend targets on every model load.
        logging = getattr(getattr(cv2, "utils", None), "logging", None)
        if logging is not None and hasattr(logging, "setLogLevel"):
            logging.setLogLevel(logging.LOG_LEVEL_ERROR)
        if not MODEL_PATH.is_file():
            raise MediaError(f"Face detection model is missing: {MODEL_PATH}")
        self.width, self.height = width, height
        self._net = cv2.FaceDetectorYN.create(str(MODEL_PATH), "", (width, height), SCORE_THRESHOLD, NMS_THRESHOLD, 50)

    def detect(self, frame: np.ndarray) -> list[Face]:
        _, faces = self._net.detect(frame)
        if faces is None:
            return []
        return [
            Face(x=float(f[0]) / self.width, y=float(f[1]) / self.height, w=float(f[2]) / self.width,
                 h=float(f[3]) / self.height, score=float(f[14]))
            for f in faces
        ]  # fmt: skip


def video_size(ffprobe: str, path: Path) -> tuple[int, int]:
    out = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of", "json", str(path)],
        capture_output=True, text=True, creationflags=NO_WINDOW,
    ).stdout  # fmt: skip
    stream = json.loads(out or "{}").get("streams", [{}])[0]
    if "width" not in stream:
        raise MediaError("Could not read the preview video")
    return int(stream["width"]), int(stream["height"])


def sample_frames(
    ffmpeg: str, proxy: Path, width: int, height: int, start_ms: int, end_ms: int, cancel: CancelToken
) -> Iterator[tuple[int, np.ndarray]]:
    """(source time ms, BGR frame) at SAMPLE_FPS between start and end."""
    proc = subprocess.Popen(
        [ffmpeg, "-v", "error", "-nostdin", "-ss", f"{start_ms / 1000:.3f}", "-i", str(proxy),
         "-t", f"{(end_ms - start_ms) / 1000:.3f}", "-an", "-vf", f"fps={SAMPLE_FPS}",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW,
    )  # fmt: skip
    size = width * height * 3
    step = 1000 / SAMPLE_FPS
    assert proc.stdout is not None
    try:
        i = 0
        while True:
            if cancel.cancelled:
                raise Cancelled()
            data = proc.stdout.read(size)
            if len(data) < size:
                break
            yield round(start_ms + i * step), np.frombuffer(data, dtype=np.uint8).reshape(height, width, 3)
            i += 1
    finally:
        proc.kill()
        proc.wait()
