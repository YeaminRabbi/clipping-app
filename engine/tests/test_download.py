from app.media.download import friendly_error


def test_known_errors_are_translated():
    raw = "[generic] missing: Unable to download webpage: HTTP Error 404: File not found (caused by <HTTPError 404>)"
    assert "404" in friendly_error(raw) and "Check the address" in friendly_error(raw)
    assert "isn't a video page" in friendly_error("Unsupported URL: https://example.com/")
    assert "private" in friendly_error("[youtube] abc: Private video. Sign in if you've been granted access")


def test_unknown_errors_are_cleaned_up():
    raw = "[vimeo] 123: Something odd happened (caused by <Weird>)"
    assert friendly_error(raw) == "Something odd happened"
