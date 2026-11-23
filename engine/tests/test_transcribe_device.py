"""Choosing where speech recognition runs. CTranslate2 only looks for cuBLAS when it first computes
something, so a model can load on the GPU and then fail: the CPU fallback must cover that too."""

import numpy as np
import pytest

from app.analysis import transcribe as tr


class FakeModel:
    """WhisperModel that loads anywhere but can fail when it computes on the GPU."""

    created: list[str] = []
    fail_on_gpu = True

    def __init__(self, name, device, compute_type, download_root):
        self.device = device
        FakeModel.created.append(device)

    def transcribe(self, audio, **kwargs):
        assert isinstance(audio, np.ndarray)

        def segments():
            if self.device == "cuda" and FakeModel.fail_on_gpu:
                raise RuntimeError("Library cublas64_12.dll is not found or cannot be loaded")
            yield from ()

        return segments(), None  # lazy, like the real one


@pytest.fixture
def gpu(monkeypatch):
    monkeypatch.setattr("ctranslate2.get_cuda_device_count", lambda: 1)
    monkeypatch.setattr("faster_whisper.WhisperModel", FakeModel)
    monkeypatch.setattr(tr, "_gpu_failure", None)
    monkeypatch.setattr(tr, "_library_loads", lambda name: True)
    FakeModel.created, FakeModel.fail_on_gpu = [], True


def test_falls_back_to_cpu_when_the_gpu_fails_at_the_first_computation(gpu, tmp_path):
    model = tr._load_model(tmp_path, "tiny")
    assert model.device == "cpu" and FakeModel.created == ["cuda", "cpu"]
    where = tr.speech_device()
    assert where.device == "cpu" and where.gpu_present and "cublas64_12.dll" in where.message
    # It's remembered: later transcriptions don't try the GPU again.
    tr._load_model(tmp_path, "tiny")
    assert FakeModel.created == ["cuda", "cpu", "cpu"]
    assert "CPU" in tr.transcribing_stage()


def test_missing_cuda_library_is_detected_before_loading_a_model(gpu, tmp_path, monkeypatch):
    monkeypatch.setattr(tr, "_library_loads", lambda name: False)
    where = tr.speech_device()
    assert where.device == "cpu" and tr.CUBLAS_LIBRARY in where.message
    assert tr._load_model(tmp_path, "tiny").device == "cpu"
    assert FakeModel.created == ["cpu"], "the GPU isn't even tried"


def test_working_gpu_is_used(gpu, tmp_path):
    FakeModel.fail_on_gpu = False
    assert tr._load_model(tmp_path, "tiny").device == "cuda"
    assert tr.speech_device().message is None and tr.transcribing_stage() == "Transcribing speech"


def test_no_gpu_means_cpu_without_a_warning(gpu, monkeypatch):
    monkeypatch.setattr("ctranslate2.get_cuda_device_count", lambda: 0)
    assert tr.speech_device() == tr.SpeechDevice("cpu", False, None)


def test_health_reports_the_speech_device(client):
    speech = client.get("/health").json()["speech"]
    assert speech["device"] in ("cpu", "cuda") and set(speech) == {"device", "gpu_present", "message"}
