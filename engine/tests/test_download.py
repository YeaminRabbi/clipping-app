import http.server
import threading

import pytest

from app.media import CancelToken, Cancelled, MediaError
from app.media.download import download, friendly_error


def test_known_errors_are_translated():
    raw = "[generic] missing: Unable to download webpage: HTTP Error 404: File not found (caused by <HTTPError 404>)"
    assert "404" in friendly_error(raw) and "Check the address" in friendly_error(raw)
    assert "isn't a video page" in friendly_error("Unsupported URL: https://example.com/")
    assert "private" in friendly_error("[youtube] abc: Private video. Sign in if you've been granted access")


def test_unknown_errors_are_cleaned_up():
    raw = "[vimeo] 123: Something odd happened (caused by <Weird>)"
    assert friendly_error(raw) == "Something odd happened"


class Site(http.server.BaseHTTPRequestHandler):
    """A page with several videos, one with a single video, a redirect, and the videos."""

    fetched: list[str] = []

    def log_message(self, *args):
        pass

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        if self.path == "/moved":
            self.send_response(302)
            self.send_header("Location", "/v0.mp4")
            self.end_headers()
            return
        if self.path.endswith(".mp4"):
            if self.command == "GET":
                Site.fetched.append(self.path)
            kind, body = "video/mp4", b"\x00\x00\x00\x18ftypmp42" + b"\0" * 20000
        else:
            count = 1 if self.path == "/one" else 4
            videos = "".join(f"<video src='/v{i}.mp4' type='video/mp4'></video>" for i in range(count))
            kind, body = "text/html", f"<html><head><title>Page</title></head><body>{videos}</body></html>".encode()
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)


@pytest.fixture
def site():
    Site.fetched = []
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Site)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_a_link_with_several_videos_is_refused_before_downloading(site, tmp_path):
    with pytest.raises(MediaError, match="more than one video"):
        download(f"{site}/list", tmp_path, "ffmpeg", CancelToken())
    # yt-dlp may read the first bytes of a file to see what it is, but nothing is saved.
    assert list(tmp_path.iterdir()) == [] and len(set(Site.fetched)) <= 1


@pytest.mark.parametrize("path", ["/one", "/v0.mp4", "/moved"])
def test_single_videos_download(site, tmp_path, path):
    titles = []
    result = download(f"{site}{path}", tmp_path, "ffmpeg", CancelToken(), on_title=titles.append)
    assert result.path.name == "original.mp4" and result.path.stat().st_size > 20000
    assert titles and result.title


def test_cancelling_before_the_download_starts(site, tmp_path):
    token = CancelToken()
    token.cancel()
    with pytest.raises(Cancelled):
        download(f"{site}/one", tmp_path, "ffmpeg", token)
    assert list(tmp_path.iterdir()) == []
