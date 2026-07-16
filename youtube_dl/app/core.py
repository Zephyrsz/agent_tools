from __future__ import annotations

import json
import os
import re
import shutil
import stat
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urlparse


APP_HOME = Path(os.environ.get("TUBESAFE_HOME", Path.home() / ".config" / "tubesafe"))
CONFIG_PATH = APP_HOME / "config.json"
MANAGED_COOKIES_PATH = APP_HOME / "cookies.txt"
DEFAULT_DOWNLOAD_DIR = Path.home() / "Downloads" / "TubeSafe"
MAX_COOKIE_FILE_BYTES = 2 * 1024 * 1024

YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
}
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,32}$")
SUPPORTED_COOKIE_BROWSERS = {"brave", "chrome", "chromium", "edge", "firefox", "safari"}


@dataclass(slots=True)
class Settings:
    download_dir: str = str(DEFAULT_DOWNLOAD_DIR)
    connections: int = 4
    sleep_min: int = 3
    sleep_max: int = 7
    proxy_url: str = ""
    cookies_path: str = ""
    cookies_browser: str = ""

    @classmethod
    def load(cls) -> "Settings":
        if not CONFIG_PATH.exists():
            return cls()
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        allowed = {key: data[key] for key in cls.__dataclass_fields__ if key in data}
        return cls(**allowed).validated()

    def validated(self) -> "Settings":
        self.connections = min(4, max(1, int(self.connections)))
        self.sleep_min = min(30, max(0, int(self.sleep_min)))
        self.sleep_max = min(60, max(self.sleep_min, int(self.sleep_max)))
        download_path = Path(self.download_dir).expanduser().resolve()
        self.download_dir = str(download_path)
        self.cookies_path = str(Path(self.cookies_path).expanduser().resolve()) if self.cookies_path else ""
        self.cookies_browser = self.cookies_browser.strip().lower()
        if self.cookies_browser not in SUPPORTED_COOKIE_BROWSERS | {""}:
            raise ValueError("不支持所选浏览器 Cookie 来源")
        if self.proxy_url:
            parsed = urlparse(self.proxy_url)
            if parsed.scheme not in {"http", "https", "socks4", "socks5", "socks5h"} or not parsed.hostname:
                raise ValueError("代理地址必须是有效的 HTTP(S) 或 SOCKS URL")
        return self

    def save(self) -> None:
        self.validated()
        APP_HOME.mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        CONFIG_PATH.chmod(stat.S_IRUSR | stat.S_IWUSR)

    def public(self) -> dict[str, object]:
        cookie_path = Path(self.cookies_path).resolve() if self.cookies_path else None
        managed_path = MANAGED_COOKIES_PATH.resolve()
        return {
            "download_dir": self.download_dir,
            "connections": self.connections,
            "sleep_min": self.sleep_min,
            "sleep_max": self.sleep_max,
            "proxy_configured": bool(self.proxy_url),
            "cookies_path": self.cookies_path,
            "cookies_browser": self.cookies_browser,
            "cookies_managed": cookie_path == managed_path,
            "cookies_file_name": cookie_path.name if cookie_path and cookie_path.is_file() else "",
            "cookies_configured": bool(
                self.cookies_browser or (self.cookies_path and Path(self.cookies_path).is_file())
            ),
        }


def validate_netscape_cookies(data: bytes) -> str:
    if not data:
        raise ValueError("Cookie 文件为空")
    if len(data) > MAX_COOKIE_FILE_BYTES:
        raise ValueError("Cookie 文件不能超过 2 MB")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("Cookie 文件必须是 UTF-8 文本") from exc

    valid_rows = 0
    youtube_rows = 0
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or (line.startswith("#") and not line.startswith("#HttpOnly_")):
            continue
        if line.startswith("#HttpOnly_"):
            line = line.removeprefix("#HttpOnly_")
        columns = line.split("\t")
        if len(columns) != 7:
            continue
        valid_rows += 1
        domain = columns[0].lstrip(".").lower()
        if domain == "youtube.com" or domain.endswith(".youtube.com"):
            youtube_rows += 1

    if valid_rows == 0:
        raise ValueError("不是有效的 Netscape Cookie 文件")
    if youtube_rows == 0:
        raise ValueError("Cookie 文件中没有 youtube.com 记录")
    return text


def store_managed_cookies(data: bytes) -> Path:
    text = validate_netscape_cookies(data)
    APP_HOME.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=APP_HOME,
            prefix="cookies-",
            suffix=".tmp",
            delete=False,
        ) as handle:
            handle.write(text)
            temp_path = Path(handle.name)
        temp_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        temp_path.replace(MANAGED_COOKIES_PATH)
        MANAGED_COOKIES_PATH.chmod(stat.S_IRUSR | stat.S_IWUSR)
        return MANAGED_COOKIES_PATH
    finally:
        if temp_path and temp_path.exists():
            temp_path.unlink(missing_ok=True)


def normalize_youtube_url(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("请输入 YouTube 视频链接")
    parsed = urlparse(value if "://" in value else f"https://{value}")
    host = (parsed.hostname or "").lower()
    if host not in YOUTUBE_HOSTS:
        raise ValueError("仅支持 youtube.com 与 youtu.be 链接")

    video_id = ""
    if host == "youtu.be":
        video_id = parsed.path.strip("/").split("/")[0]
    elif parsed.path == "/watch":
        from urllib.parse import parse_qs

        video_id = parse_qs(parsed.query).get("v", [""])[0]
    elif parsed.path.startswith(("/shorts/", "/live/", "/embed/")):
        video_id = parsed.path.strip("/").split("/")[1]
    if not VIDEO_ID_RE.fullmatch(video_id):
        raise ValueError("未识别到有效的视频 ID")
    return f"https://www.youtube.com/watch?v={video_id}"


def dependency_status() -> dict[str, dict[str, object]]:
    return {
        "yt_dlp": {"ok": shutil.which("yt-dlp") is not None, "label": "yt-dlp"},
        "aria2c": {"ok": shutil.which("aria2c") is not None, "label": "aria2c"},
        "ffmpeg": {"ok": shutil.which("ffmpeg") is not None, "label": "ffmpeg"},
    }
