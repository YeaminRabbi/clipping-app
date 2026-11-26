from pathlib import Path

from app.media import live


def test_stream_format_prefers_h264_hls_and_caps_height():
    fmt = live.stream_format("720")
    assert fmt.startswith("best[protocol^=m3u8][vcodec^=avc1][height<=720]")
    assert fmt.endswith("/best")
    assert "[height" not in live.stream_format("source").split("/")[0]


def test_record_command_writes_recording_and_preview():
    stream = live.LiveStream("https://example.com/live.m3u8", {"User-Agent": "x", "Bad": "a\r\nb"}, "t", "c", "avc1", 1080)
    cmd = live.record_command("ffmpeg", stream, Path("/tmp/part001.ts"), Path("/tmp/preview"))
    assert cmd[cmd.index("-i") + 1] == "https://example.com/live.m3u8"
    assert cmd[cmd.index("-headers") + 1] == "User-Agent: x\r\n"  # header values with line breaks are dropped
    assert str(Path("/tmp/part001.ts")) in cmd
    assert cmd[-1] == live.PREVIEW_PLAYLIST
    assert "aac_adtstoasc" in cmd and cmd.count("copy") == 2  # copied, never re-encoded


def test_finish_command_single_part_and_concat():
    one = live.finish_command("ffmpeg", [Path("/a.ts")], Path("/l.txt"), Path("/out.mp4"))
    assert "concat" not in one and str(Path("/a.ts")) in one
    many = live.finish_command("ffmpeg", [Path("/a.ts"), Path("/b.ts")], Path("/l.txt"), Path("/out.mp4"))
    assert many[many.index("-f") + 1] == "concat" and str(Path("/l.txt")) in many


def test_concat_list_escapes_quotes():
    text = live.concat_list([Path("/x/it's.ts")])
    assert text == "file '" + str(Path("/x/it's.ts")).replace("'", "'\\''") + "'\n"


def test_recording_name_is_safe():
    assert live.recording_name('a<b>:c"d/e\\f|g?h*', "2026-11-26 20-45") == "abcdefgh - 2026-11-26 20-45.mp4"
    assert live.recording_name(None, "x") == "Live stream - x.mp4"


def test_preview_files_are_restricted():
    ok = ["index.m3u8", "init.mp4", "seg00012.m4s"]
    bad = ["../state.json", "part001.ts", "seg1.m4s", "index.m3u8.tmp"]
    assert all(live.PREVIEW_FILE_RE.match(n) for n in ok)
    assert not any(live.PREVIEW_FILE_RE.match(n) for n in bad)
