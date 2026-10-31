"""Speech-to-text with faster-whisper, producing word-level timestamps."""

import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from ..ffmpeg import NO_WINDOW
from ..media import CancelToken, Cancelled, MediaError

SAMPLE_RATE = 16000
MODELS = ("tiny", "base", "small")  # fast / balanced / accurate
DEFAULT_MODEL = "base"

# huggingface_hub warns about symlinks on Windows; the fallback works fine.
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")


def decode_audio(ffmpeg: str, media: Path) -> np.ndarray:
    """Mono 16 kHz float samples. Decoding with our FFmpeg handles every format the app imports."""
    result = subprocess.run(
        [ffmpeg, "-v", "error", "-nostdin", "-i", str(media), "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-f", "f32le", "-"],
        capture_output=True,
        creationflags=NO_WINDOW,
    )
    if result.returncode != 0:
        raise MediaError("Could not read the audio track for transcription")
    return np.frombuffer(result.stdout, dtype=np.float32)


def model_is_downloaded(models_dir: Path, name: str) -> bool:
    snapshots = models_dir / f"models--Systran--faster-whisper-{name}" / "snapshots"
    return snapshots.is_dir() and any((s / "model.bin").is_file() for s in snapshots.iterdir())


def _load_model(models_dir: Path, name: str):
    import ctranslate2
    from faster_whisper import WhisperModel

    if ctranslate2.get_cuda_device_count() > 0:
        try:
            return WhisperModel(name, device="cuda", compute_type="float16", download_root=str(models_dir))
        except Exception:
            pass  # fall back to CPU, e.g. when CUDA libraries are missing
    return WhisperModel(name, device="cpu", compute_type="int8", download_root=str(models_dir))


def load_cached(path: Path, model: str, language: str | None) -> dict[str, Any] | None:
    """A saved transcript is reused when it came from the same or a more accurate model."""
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if data.get("model") not in MODELS or MODELS.index(data["model"]) < MODELS.index(model):
        return None
    if language and data.get("language") != language:
        return None
    return data


def transcribe(
    ffmpeg: str,
    media: Path,
    duration_ms: int,
    models_dir: Path,
    model: str,
    language: str | None,
    cancel: CancelToken,
    on_progress: Callable[[float], None] | None = None,
) -> dict[str, Any]:
    """Returns {"model", "language", "words": [{"start", "end", "text"}]} with times in ms."""
    models_dir.mkdir(parents=True, exist_ok=True)
    audio = decode_audio(ffmpeg, media)
    cancel.raise_if_cancelled()
    try:
        whisper = _load_model(models_dir, model)
    except Exception as err:
        raise MediaError(f"Could not load the speech model ({err}). Check your internet connection for the first download.") from err

    segments, info = whisper.transcribe(
        audio,
        language=language or None,
        word_timestamps=True,
        vad_filter=True,
        condition_on_previous_text=False,  # reduces repeated-phrase hallucinations on long files
    )
    words: list[dict[str, Any]] = []
    for segment in segments:  # lazy: the work happens while iterating
        if cancel.cancelled:
            raise Cancelled()
        for w in segment.words or []:
            text = w.word.strip()
            if text:
                words.append({"start": round(w.start * 1000), "end": round(w.end * 1000), "text": text})
        if on_progress and duration_ms:
            on_progress(min(1.0, segment.end * 1000 / duration_ms))
    return {"model": model, "language": info.language, "words": words}
