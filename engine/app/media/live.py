"""Live streams: find the stream behind a Twitch or YouTube link, and the FFmpeg command that records it.

Recording copies the broadcast as it is (no re-encoding), so it costs almost no CPU or GPU. The same FFmpeg
process also writes a short rolling HLS playlist (fragmented MP4) that the app's player reads from this
machine, so the stream is downloaded once for both.
"""

import re
from dataclasses import dataclass
from pathlib import Path

import yt_dlp
from yt_dlp.utils import DownloadError

from . import MediaError
from .download import _Logger, friendly_error

QUALITIES = ("source", "1080", "720")

# Preview playlist: 2 s fragments, the last 8 kept (older ones deleted as new ones arrive).
PREVIEW_SEGMENT_S = 2
PREVIEW_LIST_SIZE = 8
PREVIEW_PLAYLIST = "index.m3u8"
PREVIEW_INIT = "init.mp4"
PREVIEW_SEGMENT_PATTERN = "seg%05d.m4s"
PREVIEW_FILE_RE = re.compile(r"^(index\.m3u8|init\.mp4|seg\d{5}\.m4s)$")

_OFFLINE = re.compile(r"not (currently )?live|is offline|offline|will begin|premieres in|scheduled|has ended|no longer live", re.I)


@dataclass
class LiveStream:
    url: str
    headers: dict[str, str]
    title: str | None
    channel: str | None
    vcodec: str | None
    height: int | None


def stream_format(quality: str) -> str:
    """HLS only (it's what both sites serve live), preferring H.264 so the in-app player can show it."""
    cap = "" if quality == "source" else f"[height<={int(quality)}]"
    return "/".join(
        [
            f"best[protocol^=m3u8][vcodec^=avc1]{cap}",
            f"best[protocol^=m3u8]{cap}",
            "best[protocol^=m3u8]",
            "best",
        ]
    )


def resolve(url: str, quality: str) -> LiveStream:
    """What is live at this link right now. Raises MediaError if nothing is (or the link isn't a stream)."""
    if quality not in QUALITIES:
        quality = "source"
    logger = _Logger()
    opts = {
        "format": stream_format(quality),
        "noplaylist": True,
        "logger": logger,
        "noprogress": True,
        "quiet": True,
        "socket_timeout": 20,
        "skip_download": True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except DownloadError as err:
        message = logger.last_error or str(err)
        if _OFFLINE.search(message):
            raise MediaError("This channel isn't live right now.") from err
        raise MediaError(friendly_error(message)) from err

    info = info or {}
    if info.get("_type") == "playlist":
        raise MediaError("This link is a channel page or playlist. Paste the link of the live stream itself.")
    if not (info.get("is_live") or info.get("live_status") == "is_live"):
        raise MediaError("This link isn't live right now. To bring in a finished stream, use Import link on a project instead.")
    stream_url = info.get("url")
    if not stream_url:
        raise MediaError("The stream was found but couldn't be opened. Try again in a moment.")
    return LiveStream(
        url=stream_url,
        headers={k: v for k, v in (info.get("http_headers") or {}).items() if isinstance(v, str)},
        title=info.get("title") or info.get("description"),
        channel=info.get("uploader") or info.get("channel") or info.get("uploader_id"),
        vcodec=info.get("vcodec"),
        height=info.get("height"),
    )


def record_command(ffmpeg: str, stream: LiveStream, part_path: Path, preview_dir: Path) -> list[str]:
    """One FFmpeg process, two outputs: the recording (MPEG-TS, which survives a crash) and the preview.

    The preview paths are relative, so run it with cwd=preview_dir.
    """
    headers = "".join(f"{k}: {v}\r\n" for k, v in stream.headers.items() if "\r" not in v and "\n" not in v)
    command = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostats"]
    if headers:
        command += ["-headers", headers]
    command += [
        "-rw_timeout", "20000000",  # 20 s without data counts as a dropped connection
        "-i", stream.url,
        # Recording: video and audio exactly as broadcast.
        "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy",
        "-f", "mpegts", str(part_path),
        # Preview for the in-app player. Live HLS audio is AAC in ADTS framing, which MP4 fragments
        # need converted (copied, not re-encoded).
        "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy", "-bsf:a", "aac_adtstoasc",
        "-f", "hls",
        "-hls_time", str(PREVIEW_SEGMENT_S),
        "-hls_list_size", str(PREVIEW_LIST_SIZE),
        "-hls_flags", "delete_segments+omit_endlist",
        "-hls_segment_type", "fmp4",
        "-hls_fmp4_init_filename", PREVIEW_INIT,
        "-hls_segment_filename", PREVIEW_SEGMENT_PATTERN,
        PREVIEW_PLAYLIST,
    ]  # fmt: skip
    _ = preview_dir  # documented above: the caller runs FFmpeg inside it
    return command


def finish_command(ffmpeg: str, parts: list[Path], list_file: Path, output: Path) -> list[str]:
    """Join the recorded parts (one per connection) into a normal MP4, without re-encoding."""
    if len(parts) == 1:
        inputs = ["-i", str(parts[0])]
    else:
        # Written by the caller: one "file '<path>'" line per part.
        inputs = ["-f", "concat", "-safe", "0", "-i", str(list_file)]
    return [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        *inputs,
        "-map", "0:v:0", "-map", "0:a:0?", "-c", "copy",
        "-movflags", "+faststart",
        str(output),
    ]  # fmt: skip


def concat_list(parts: list[Path]) -> str:
    """The concat demuxer's list file. Quotes in paths are escaped the way the demuxer expects."""
    lines = []
    for part in parts:
        escaped = str(part).replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    return "\n".join(lines) + "\n"


_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def recording_name(channel: str | None, started: str) -> str:
    """File name for a finished recording, e.g. "somechannel - 2026-11-26 20-45.mp4"."""
    base = _UNSAFE.sub("", (channel or "Live stream").strip())[:60].strip(" .") or "Live stream"
    return f"{base} - {started}.mp4"
