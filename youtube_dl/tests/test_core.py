from pathlib import Path

import pytest

from app.core import Settings, normalize_youtube_url, validate_netscape_cookies
from app.downloader import _common_args, _format_options


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://www.youtube.com/watch?v=VhnAyq6cEjQ", "https://www.youtube.com/watch?v=VhnAyq6cEjQ"),
        ("https://youtu.be/VhnAyq6cEjQ?t=5", "https://www.youtube.com/watch?v=VhnAyq6cEjQ"),
        ("youtube.com/shorts/VhnAyq6cEjQ", "https://www.youtube.com/watch?v=VhnAyq6cEjQ"),
    ],
)
def test_normalize_youtube_url(raw: str, expected: str) -> None:
    assert normalize_youtube_url(raw) == expected


@pytest.mark.parametrize("url", ["https://example.com/watch?v=VhnAyq6cEjQ", "https://youtube.com/playlist?list=x", ""])
def test_rejects_unsupported_urls(url: str) -> None:
    with pytest.raises(ValueError):
        normalize_youtube_url(url)


def test_settings_clamp_connections(tmp_path: Path) -> None:
    settings = Settings(download_dir=str(tmp_path), connections=12, sleep_min=8, sleep_max=2).validated()
    assert settings.connections == 4
    assert settings.sleep_max == 8


def test_browser_cookie_source_takes_priority(tmp_path: Path) -> None:
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text("cookie", encoding="utf-8")
    settings = Settings(
        download_dir=str(tmp_path),
        cookies_path=str(cookie_file),
        cookies_browser="chrome",
    ).validated()
    args = _common_args(settings)
    assert args[-2:] == ["--cookies-from-browser", "chrome"]
    assert "--cookies" not in args


def test_rejects_unknown_cookie_browser(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="不支持"):
        Settings(download_dir=str(tmp_path), cookies_browser="unknown").validated()


def test_validates_netscape_youtube_cookies() -> None:
    content = b"# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\ttest\n"
    assert "youtube.com" in validate_netscape_cookies(content)


@pytest.mark.parametrize(
    "content",
    [b"", b"not-a-cookie-file", b".example.com\tTRUE\t/\tTRUE\t0\tSID\ttest\n"],
)
def test_rejects_invalid_or_unrelated_cookies(content: bytes) -> None:
    with pytest.raises(ValueError):
        validate_netscape_cookies(content)


def test_formats_prefer_mp4_and_add_audio() -> None:
    info = {
        "formats": [
            {"format_id": "137", "height": 1080, "ext": "mp4", "vcodec": "avc1", "acodec": "none", "tbr": 4000},
            {"format_id": "248", "height": 1080, "ext": "webm", "vcodec": "vp9", "acodec": "none", "tbr": 5000},
            {"format_id": "22", "height": 720, "ext": "mp4", "vcodec": "avc1", "acodec": "mp4a", "tbr": 2000},
        ]
    }
    options = _format_options(info)
    assert options[0]["id"].startswith("137+bestaudio")
    assert options[0]["needs_merge"] is True
    assert options[1]["id"] == "22"
    assert options[-1]["label"] == "仅音频"


def test_empty_formats_do_not_invent_audio_option() -> None:
    assert _format_options({"formats": []}) == []
