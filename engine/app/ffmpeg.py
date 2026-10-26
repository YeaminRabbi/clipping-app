"""Locate the FFmpeg binaries and report what they can do."""

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

EXE = ".exe" if os.name == "nt" else ""

# Hardware H.264/H.265 encoders we can use for export, by vendor.
HW_ENCODERS = {
    "nvidia": ["h264_nvenc", "hevc_nvenc"],
    "intel": ["h264_qsv", "hevc_qsv"],
    "amd": ["h264_amf", "hevc_amf"],
    "apple": ["h264_videotoolbox", "hevc_videotoolbox"],
}


@dataclass
class ToolInfo:
    path: str | None
    version: str | None
    source: str | None  # "env", "bundled" or "system"


@dataclass
class FFmpegInfo:
    ffmpeg: ToolInfo
    ffprobe: ToolInfo
    hw_encoders: dict[str, list[str]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return bool(self.ffmpeg.path and self.ffprobe.path)


def _run(args: list[str], timeout: float = 10) -> str:
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, creationflags=flags)
    return result.stdout


def resolve_tool(name: str, bin_dir: Path) -> tuple[str | None, str | None]:
    """Find a binary: an explicit env override first, then the bundled copy, then PATH."""
    override = os.environ.get(f"CLIP_{name.upper()}_PATH")
    if override and Path(override).is_file():
        return override, "env"
    bundled = bin_dir / f"{name}{EXE}"
    if bundled.is_file():
        return str(bundled), "bundled"
    found = shutil.which(name)
    if found:
        return found, "system"
    return None, None


def _version(path: str) -> str | None:
    try:
        first_line = _run([path, "-version"]).splitlines()[0]
    except (OSError, subprocess.SubprocessError, IndexError):
        return None
    match = re.search(r"version\s+(\S+)", first_line)
    return match.group(1) if match else first_line


def _hw_encoders(ffmpeg_path: str) -> dict[str, list[str]]:
    """Encoders compiled into this FFmpeg build. Whether the GPU is present is checked at export time."""
    try:
        listing = _run([ffmpeg_path, "-hide_banner", "-encoders"])
    except (OSError, subprocess.SubprocessError):
        return {}
    available = set(re.findall(r"^\s*V\S*\s+(\S+)", listing, flags=re.MULTILINE))
    found = {vendor: [e for e in names if e in available] for vendor, names in HW_ENCODERS.items()}
    return {vendor: names for vendor, names in found.items() if names}


@lru_cache(maxsize=1)
def detect(bin_dir: Path) -> FFmpegInfo:
    tools = {}
    for name in ("ffmpeg", "ffprobe"):
        path, source = resolve_tool(name, bin_dir)
        tools[name] = ToolInfo(path=path, version=_version(path) if path else None, source=source)
    info = FFmpegInfo(ffmpeg=tools["ffmpeg"], ffprobe=tools["ffprobe"])
    if info.ffmpeg.path:
        info.hw_encoders = _hw_encoders(info.ffmpeg.path)
    return info
