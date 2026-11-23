import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import yt_dlp
from yt_dlp.utils import DownloadError

from . import CancelToken, Cancelled, MediaError

# Best video up to 4K plus best audio; fall back to a single combined file.
FORMAT = "bv*[height<=2160]+ba/b[height<=2160]/bv*+ba/b"


@dataclass
class DownloadResult:
    path: Path
    title: str | None


_FRIENDLY_ERRORS = [
    (re.compile(r"HTTP Error 404", re.I), "Nothing was found at this link (404). Check the address and try again."),
    (re.compile(r"HTTP Error 40[13]", re.I), "The site refused access to this video (it may be private or need a sign-in)."),
    (re.compile(r"Unsupported URL", re.I), "This link isn't a video page the app can download from."),
    (re.compile(r"private video|sign in|login required|members-only", re.I), "This video is private or needs a sign-in, so it can't be downloaded."),
    (re.compile(r"not available in your country|geo.?restrict", re.I), "This video isn't available in your region."),
    (re.compile(r"getaddrinfo|Name or service not known|Failed to resolve|timed out", re.I), "Couldn't reach the site. Check your internet connection."),
]  # fmt: skip


def friendly_error(message: str) -> str:
    """Turn a yt-dlp error into something a user can act on, keeping the original if unrecognized."""
    for pattern, friendly in _FRIENDLY_ERRORS:
        if pattern.search(message):
            return friendly
    # Drop the "[extractor] id: " prefix and the "(caused by ...)" tail.
    message = re.sub(r"^\[[^\]]+\]\s*[^:]*:\s*", "", message)
    return re.sub(r"\s*\(caused by .*\)$", "", message).strip() or "Download failed"


class _Logger:
    """Collect yt-dlp messages instead of printing them; the last error is shown to the user."""

    def __init__(self) -> None:
        self.last_error: str | None = None

    def debug(self, msg: str) -> None:
        pass

    def info(self, msg: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        pass

    def error(self, msg: str) -> None:
        self.last_error = msg.removeprefix("ERROR: ")


def download(
    url: str,
    dest_dir: Path,
    ffmpeg: str,
    cancel: CancelToken,
    on_progress: Callable[[float], None] | None = None,
    on_title: Callable[[str], None] | None = None,
) -> DownloadResult:
    """Download a video page or direct media URL into dest_dir as original.<ext>."""
    logger = _Logger()
    # Separate video and audio downloads each report 0..100%; weight them so progress never goes backwards.
    state = {"index": 0, "count": 1, "title_sent": False}

    def hook(d: dict) -> None:
        cancel.raise_if_cancelled()
        info = d.get("info_dict") or {}
        if on_title and not state["title_sent"] and info.get("title"):
            state["title_sent"] = True
            on_title(info["title"])
        if d["status"] == "downloading" and on_progress:
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            if total:
                count = len(info.get("requested_formats") or []) or 1
                index = state["index"]
                on_progress(min(1.0, (index + d.get("downloaded_bytes", 0) / total) / count))
        elif d["status"] == "finished":
            state["index"] += 1

    opts = {
        "format": FORMAT,
        "outtmpl": str(dest_dir / "original.%(ext)s"),
        "merge_output_format": "mp4/mkv",
        "noplaylist": True,
        "ffmpeg_location": ffmpeg,
        "progress_hooks": [hook],
        "logger": logger,
        "noprogress": True,
        "overwrites": True,
        "retries": 3,
        "socket_timeout": 30,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
    except Cancelled:
        raise
    except DownloadError as err:
        if cancel.cancelled:
            raise Cancelled() from err
        raise MediaError(friendly_error(logger.last_error or str(err))) from err

    downloads = (info or {}).get("requested_downloads") or []
    path = Path(downloads[0]["filepath"]) if downloads and downloads[0].get("filepath") else None
    if path is None or not path.is_file():
        raise MediaError("Download finished but no video file was produced")
    return DownloadResult(path=path, title=(info or {}).get("title"))
