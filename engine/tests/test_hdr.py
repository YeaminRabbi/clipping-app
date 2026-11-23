"""HDR sources come out as ordinary SDR video with the colors they should have (F-25)."""

import subprocess
import time
from pathlib import Path

import numpy as np
import pytest

from app.ffmpeg import detect
from app.media.color import tone_map_filter
from app.media.probe import probe
from conftest import BIN_DIR, FFMPEG, FFPROBE, needs_ffmpeg, wait_for

COLORS = ["C04030", "30A050", "3050C0", "E0E0E0", "808080", "D0A080"]
CENTERS = [(y, x) for y in (120, 360) for x in (160, 480, 800)]
BT709 = "setparams=color_primaries=bt709:color_trc=bt709:colorspace=bt709:range=tv"
needs_tone_map = pytest.mark.skipif(not detect(BIN_DIR).can_tone_map, reason="this FFmpeg has no zscale/tonemap")


@pytest.fixture(scope="module")
def videos(tmp_path_factory) -> dict[str, Path]:
    """The same six color patches in SDR, HLG and PQ."""
    d = tmp_path_factory.mktemp("hdr")
    inputs = [a for c in COLORS for a in ("-f", "lavfi", "-i", f"color=0x{c}:s=320x240:r=30:d=2")]
    subprocess.run(
        [FFMPEG, "-v", "error", "-y", *inputs, "-filter_complex",
         f"[0][1][2]hstack=3[t];[3][4][5]hstack=3[u];[t][u]vstack,scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,{BT709}",
         "-c:v", "libx264", "-qp", "4", str(d / "sdr.mp4")],
        check=True,
    )  # fmt: skip
    for name, transfer in (("hlg", "arib-std-b67"), ("pq", "smpte2084")):
        subprocess.run(
            [FFMPEG, "-v", "error", "-y", "-i", str(d / "sdr.mp4"), "-vf",
             f"zscale=t=linear:npl=203,format=gbrpf32le,zscale=p=bt2020:t={transfer}:m=bt2020nc:r=tv:npl=203,format=yuv420p10le",
             "-c:v", "libx265", "-x265-params", f"log-level=error:qp=6:colorprim=bt2020:transfer={transfer}:colormatrix=bt2020nc",
             "-tag:v", "hvc1", str(d / f"{name}.mp4")],
            check=True, capture_output=True,
        )  # fmt: skip
    return {p.stem: p for p in d.glob("*.mp4")}


def patches(path, height: int = 480) -> np.ndarray:
    """Patch colors as a player without HDR shows them."""
    raw = subprocess.run(
        [FFMPEG, "-v", "error", "-ss", "0.5", "-i", str(path), "-frames:v", "1", "-vf",
         f"{BT709},scale=960:{height}:in_color_matrix=bt709,format=rgb24", "-f", "rawvideo", "-"],
        capture_output=True, check=True,
    ).stdout  # fmt: skip
    frame = np.frombuffer(raw, np.uint8).reshape(height, 960, 3)
    margin = (height - 480) // 2
    return np.array([frame[y + margin, x] for y, x in CENTERS]).astype(int)


def transfer_of(path) -> str:
    return probe(FFPROBE, Path(path)).color_transfer


def test_only_hdr_is_tone_mapped():
    assert tone_map_filter("bt709") == tone_map_filter(None) == ""
    assert "tonemap" in tone_map_filter("smpte2084") and "tonemap" in tone_map_filter("arib-std-b67")


@needs_ffmpeg
@needs_tone_map
@pytest.mark.parametrize("kind", ["hlg", "pq", "sdr"])
@pytest.mark.parametrize("framing", ["center", "fit"])
def test_exports_and_previews_have_the_right_colors(client, project, videos, tmp_path, kind, framing):
    assert transfer_of(videos["hlg"]) == "arib-std-b67"
    sid = client.post(f"/projects/{project['id']}/sources", json={"path": str(videos[kind])}).json()["id"]
    assert wait_for(client, sid, {"ready", "failed"})["status"] == "ready"
    want = patches(videos["sdr"])
    proxy = client.app.state.ingest.source_dir(project["id"], sid) / "proxy.mp4"
    assert np.abs(patches(proxy) - want).mean() < 6, "preview"

    clip = client.post(f"/sources/{sid}/clips", json={"start_ms": 0, "end_ms": 1500}).json()
    aspect = "16:9" if framing == "center" else "1:1"
    preset = {"output_dir": str(tmp_path / "out"), "hardware": False, "default_framing": framing}
    job = client.post("/exports", json={"clip_ids": [clip["id"]], "aspects": [aspect], "preset": preset}).json()[0]
    for _ in range(300):
        job = next(j for j in client.get(f"/projects/{project['id']}/exports").json() if j["id"] == job["id"])
        if job["status"] in ("done", "failed"):
            break
        time.sleep(0.1)
    assert job["status"] == "done", job["error"]
    info = probe(FFPROBE, Path(job["output_path"]))
    assert info.color_transfer in ("bt709", None)
    got = patches(job["output_path"], 960 if aspect == "1:1" else 480)
    # A 16:9 crop of this 2:1 picture keeps its middle: the outer patches' centers move, but not into others.
    assert np.abs(got - want).mean() < 8, f"{kind} {framing}: {got.tolist()}"
