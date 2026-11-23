"""Keep startup checks usable even when third-party packages are absent."""

from importlib.metadata import PackageNotFoundError

import pytest

import check_dependencies
from app.config import load_settings
from app.ffmpeg import EXE, resolve_tool


def test_dependency_check_reports_missing_and_outdated_packages(tmp_path, monkeypatch):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("numpy==2.5.4\nuvicorn[standard]==0.54.0\nfastapi==0.162.0\n")

    def version(name):
        if name == "numpy":
            raise PackageNotFoundError(name)
        return {"uvicorn": "0.53.0", "fastapi": "0.162.0"}[name]

    monkeypatch.setattr(check_dependencies.importlib.metadata, "version", version)
    assert check_dependencies.missing_requirements(requirements) == ["numpy==2.5.4", "uvicorn[standard]==0.54.0"]


def test_dev_dependency_check_follows_relative_requirements(tmp_path, monkeypatch):
    (tmp_path / "requirements.txt").write_text("numpy==2.5.4\n")
    dev = tmp_path / "requirements-dev.txt"
    dev.write_text("# Developer tools\n-r requirements.txt\npytest==9.1.1\n")
    monkeypatch.setattr(check_dependencies.importlib.metadata, "version", lambda name: "9.1.1")
    assert check_dependencies.missing_requirements(dev) == ["numpy==2.5.4"]


def test_unsupported_requirements_fail_instead_of_being_silently_ignored(tmp_path):
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("numpy>=2\n")
    with pytest.raises(ValueError, match="Unsupported requirement"):
        check_dependencies.missing_requirements(requirements)


def test_check_rejects_missing_numpy_even_with_installed_metadata(monkeypatch, capsys):
    monkeypatch.setattr(check_dependencies, "missing_requirements", lambda path: [])
    monkeypatch.setattr(check_dependencies.importlib.util, "find_spec", lambda name: None if name == "numpy" else object())
    assert check_dependencies.main() == 1
    assert "Missing module: numpy" in capsys.readouterr().out


def test_healthy_environment_passes_without_output(monkeypatch, capsys):
    monkeypatch.setattr(check_dependencies, "missing_requirements", lambda path: [])
    monkeypatch.setattr(check_dependencies.importlib.util, "find_spec", lambda name: object())
    assert check_dependencies.main() == 0
    assert capsys.readouterr().out == ""


def test_settings_use_device_environment(tmp_path, monkeypatch):
    data = tmp_path / "custom data"
    tools = tmp_path / "custom tools"
    models = tmp_path / "custom models"
    monkeypatch.setenv("CLIP_DATA_DIR", str(data))
    monkeypatch.setenv("CLIP_BIN_DIR", str(tools))
    monkeypatch.setenv("CLIP_MODELS_DIR", str(models))
    settings = load_settings()
    assert settings.db_path == data / "clipping.db"
    assert settings.projects_dir.is_dir()
    assert settings.bin_dir == tools
    assert settings.models_path == models


def test_ffmpeg_resolution_uses_override_bundle_then_device_path(tmp_path, monkeypatch):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    bundled = bundle / f"ffmpeg{EXE}"
    bundled.touch()
    override = tmp_path / f"custom-ffmpeg{EXE}"
    override.touch()
    monkeypatch.setenv("CLIP_FFMPEG_PATH", str(override))
    monkeypatch.setattr("app.ffmpeg.shutil.which", lambda name: "system-ffmpeg")
    assert resolve_tool("ffmpeg", bundle) == (str(override), "env")
    monkeypatch.delenv("CLIP_FFMPEG_PATH")
    assert resolve_tool("ffmpeg", bundle) == (str(bundled), "bundled")
    bundled.unlink()
    assert resolve_tool("ffmpeg", bundle) == ("system-ffmpeg", "system")
