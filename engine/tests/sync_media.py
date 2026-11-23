"""Sample videos with a flash and a beep once a second, and measuring how far apart they end up."""

import json
import subprocess
from pathlib import Path

import numpy as np

from conftest import FFMPEG, FFPROBE

FLASH = "color=black:s=64x64:r=60:d={d},format=gray,geq=lum='if(lt(mod(N,60),6),255,0)'"
BEEP = "aevalsrc='if(lt(mod(t,1),0.1),0.8*sin(2*PI*1000*t),0)':s=48000:d={d}"
# 60 fps for 4 s, then 15 fps for 4 s, and so on: really variable timing.
VFR = "select='if(lt(mod(t,8),4),1,not(mod(n,4)))'"


def flash_beep(path: Path, seconds: int = 20, vfr: bool = False, audio_codec: str = "aac", gop: int = 120) -> Path:
    subprocess.run(
        [FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", FLASH.format(d=seconds), "-f", "lavfi", "-i", BEEP.format(d=seconds),
         *(["-vf", VFR, "-fps_mode", "vfr"] if vfr else []),
         "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-qp", "8", "-g", str(gop), "-c:a", audio_codec, str(path)],
        check=True, capture_output=True,
    )  # fmt: skip
    return path


def av_offsets_ms(path: str | Path) -> list[float]:
    """Picture minus sound (ms) for every flash in the file."""
    pix = subprocess.run(
        [FFMPEG, "-v", "error", "-i", str(path), "-vf", "scale=1:1,format=gray", "-fps_mode", "passthrough", "-f", "rawvideo", "-"],
        capture_output=True, check=True,
    ).stdout  # fmt: skip
    out = subprocess.run(
        [FFPROBE, "-v", "error", "-select_streams", "v:0", "-show_entries", "frame=pts_time", "-of", "json", str(path)],
        capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    times = [float(f["pts_time"]) for f in json.loads(out)["frames"]]
    bright = np.frombuffer(pix, np.uint8) > 100
    flashes = [times[i] for i in range(1, min(len(bright), len(times))) if bright[i] and not bright[i - 1]]
    raw = subprocess.run(
        [FFMPEG, "-v", "error", "-i", str(path), "-af", "aresample=async=1:first_pts=0", "-ac", "1", "-ar", "48000", "-f", "f32le", "-"],
        capture_output=True, check=True,
    ).stdout  # fmt: skip
    loud = np.convolve(np.abs(np.frombuffer(raw, np.float32)), np.ones(96) / 96, "same") > 0.1
    beeps = np.flatnonzero(loud[1:] & ~loud[:-1]) / 48000
    return [(f - min(beeps, key=lambda b: abs(b - f))) * 1000 for f in flashes]
