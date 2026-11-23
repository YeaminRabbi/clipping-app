"""Speech-to-text with faster-whisper, producing word-level timestamps."""

import json
import logging
import os
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ..ffmpeg import NO_WINDOW
from ..media import CancelToken, Cancelled, MediaError

log = logging.getLogger("engine.transcribe")

SAMPLE_RATE = 16000
MODELS = ("tiny", "base", "small")  # fast / balanced / accurate
DEFAULT_MODEL = "base"
# Bump when transcripts change in a way older saved ones lack; those are then redone.
# 2: filler words ("um", "uh") are kept, so they can be cut out.
TRANSCRIPT_VERSION = 2
# Whisper tidies speech by dropping fillers; a prompt that contains them makes it write them down.
FILLER_PROMPT = "Umm, let me think like, hmm... Okay, uh, here's what I'm, um, thinking."

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


# CTranslate2 bundles most of what it needs to run on an NVIDIA GPU, but not cuBLAS.
CUBLAS_LIBRARY = "cublas64_12.dll" if sys.platform == "win32" else "libcublas.so.12"
# Why the GPU can't be used, once an attempt to use it has failed (None = no failure seen).
_gpu_failure: str | None = None


@dataclass(frozen=True)
class SpeechDevice:
    device: str  # "cuda" or "cpu"
    gpu_present: bool
    message: str | None  # shown to the user when there is a GPU that can't be used


def _library_loads(name: str) -> bool:
    import ctypes

    try:
        ctypes.CDLL(name)
    except OSError:
        return False
    return True


def speech_device() -> SpeechDevice:
    """Where speech recognition will run. Checked before loading a model, because CTranslate2 only
    looks for cuBLAS when it first computes something, long after the model has loaded."""
    import ctranslate2

    if ctranslate2.get_cuda_device_count() == 0:
        return SpeechDevice("cpu", False, None)
    if _gpu_failure is not None:
        return SpeechDevice("cpu", True, f"The NVIDIA GPU can't be used for speech recognition ({_gpu_failure}), so it runs on the CPU.")
    if not _library_loads(CUBLAS_LIBRARY):
        return SpeechDevice(
            "cpu", True, f"The CUDA 12 library {CUBLAS_LIBRARY} isn't installed, so speech recognition runs on the CPU instead of the NVIDIA GPU."
        )
    return SpeechDevice("cuda", True, None)


def transcribing_stage() -> str:
    """Progress text for a running transcription; says so when a GPU is there but isn't used."""
    where = speech_device()
    return "Transcribing speech on the CPU (GPU not usable, see System check)" if where.message else "Transcribing speech"


def _load_model(models_dir: Path, name: str):
    from faster_whisper import WhisperModel

    global _gpu_failure
    where = speech_device()
    if where.device == "cuda":
        try:
            model = WhisperModel(name, device="cuda", compute_type="float16", download_root=str(models_dir))
            # Missing or mismatched CUDA libraries only show up when something is computed, so compute
            # something now, while falling back is still possible.
            segments, _ = model.transcribe(np.zeros(SAMPLE_RATE, dtype=np.float32), language="en", beam_size=1)
            list(segments)
            return model
        except Exception as err:
            _gpu_failure = str(err).strip() or type(err).__name__
            log.warning("Speech recognition can't use the GPU, falling back to the CPU: %s", err)
    elif where.message:
        log.warning("%s", where.message)
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
    if data.get("version", 1) < TRANSCRIPT_VERSION:
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
        # English; it would pull other languages towards English.
        initial_prompt=FILLER_PROMPT if language in (None, "en") else None,
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
    return {"version": TRANSCRIPT_VERSION, "model": model, "language": info.language, "words": words}
