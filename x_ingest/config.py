"""JSON project configuration with CLI-overridable defaults."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .models import normalize_handle


DEFAULT_DATABASE = Path("./posts.sqlite3")
DEFAULT_MEDIA_ROOT = Path("./media")
DEFAULT_PROFILE_DIR = Path("./chrome-profile")
DEFAULT_CDP_URL = "http://127.0.0.1:9222"
DEFAULT_MCP_COMMAND = ("npx", "--yes", "chrome-devtools-mcp@0.13.0")


@dataclass(frozen=True)
class MySQLConfig:
    host: str = "127.0.0.1"
    port: int = 3306
    user: str = "x_ingest"
    database: str = "x_ingest"
    password: str = ""
    password_env: str = "X_INGEST_DB_PASSWORD"
    charset: str = "utf8mb4"
    connect_timeout: float = 10.0
    autocommit: bool = False

    def __post_init__(self) -> None:
        if not self.host.strip() or not self.database.strip() or not self.user.strip():
            raise ValueError("mysql host, user, and database are required")
        if not 1 <= int(self.port) <= 65535:
            raise ValueError("mysql port must be between 1 and 65535")
        if float(self.connect_timeout) <= 0:
            raise ValueError("mysql connect_timeout must be positive")

    @property
    def resolved_password(self) -> str:
        if self.password:
            return self.password
        return os.environ.get(self.password_env, "") if self.password_env else ""


@dataclass(frozen=True)
class BrowserConfig:
    cdp_url: str = DEFAULT_CDP_URL
    profile_dir: Path = DEFAULT_PROFILE_DIR
    mcp_command: tuple[str, ...] = DEFAULT_MCP_COMMAND
    mcp_timeout: float = 30.0
    headless: bool = False
    max_scrolls: int = 10000
    batch_size: int = 20
    wait_ms: int = 1200
    max_retries: int = 3
    navigate_tool: str = "navigate_page"
    evaluate_tool: str = "evaluate_script"
    new_page_tool: str = "new_page"
    select_page_tool: str = "select_page"
    close_page_tool: str = "close_page"
    list_pages_tool: str = "list_pages"

    def __post_init__(self) -> None:
        parsed = urlparse(self.cdp_url)
        if parsed.scheme not in {"http", "https", "ws", "wss"} or not parsed.netloc:
            raise ValueError("browser cdp_url must be an HTTP or WebSocket URL")
        if not self.mcp_command:
            raise ValueError("browser mcp_command cannot be empty")
        for name in ("mcp_timeout", "max_scrolls", "batch_size", "wait_ms", "max_retries"):
            if float(getattr(self, name)) <= 0:
                raise ValueError(f"browser {name} must be positive")


@dataclass(frozen=True)
class UserConfig:
    handle: str
    relation: str = "own_post"
    enabled: bool = True


@dataclass(frozen=True)
class AppConfig:
    database: Path = DEFAULT_DATABASE
    mysql: MySQLConfig = field(default_factory=MySQLConfig)
    vault: Path | None = None
    media_root: Path = DEFAULT_MEDIA_ROOT
    browser: BrowserConfig = field(default_factory=BrowserConfig)
    obsidian_folder: str = "X Clips"
    users: dict[str, UserConfig] = field(default_factory=dict)

    def user(self, handle: str) -> UserConfig:
        key = normalize_handle(handle)
        return self.users.get(key, UserConfig(handle=key))


def load_config(path: str | Path | None) -> AppConfig:
    if path is None:
        return AppConfig()
    config_path = Path(path).expanduser().resolve()
    data: dict[str, Any] = json.loads(config_path.read_text(encoding="utf-8"))
    config_dir = config_path.parent

    def config_path_value(value: Any, default: Path) -> Path:
        resolved = Path(value if value is not None else default).expanduser()
        return resolved if resolved.is_absolute() else (config_dir / resolved).resolve()

    obsidian = data.get("obsidian") if isinstance(data.get("obsidian"), dict) else {}
    users: dict[str, UserConfig] = {}
    for item in data.get("users", []):
        if not isinstance(item, dict):
            continue
        handle = normalize_handle(str(item.get("handle", "")))
        if handle:
            users[handle] = UserConfig(
                handle=handle,
                relation=str(item.get("relation", "own_post")),
                enabled=bool(item.get("enabled", True)),
            )
    mysql_data = data.get("mysql") if isinstance(data.get("mysql"), dict) else {}
    password_value = str(mysql_data.get("password", ""))
    password_env = str(mysql_data.get("password_env", "X_INGEST_DB_PASSWORD"))
    mysql = MySQLConfig(
        host=str(mysql_data.get("host", "127.0.0.1")),
        port=int(mysql_data.get("port", 3306)),
        user=str(mysql_data.get("user", "x_ingest")),
        database=str(mysql_data.get("database", "x_ingest")),
        password=password_value or os.environ.get(password_env, ""),
        password_env=password_env,
        charset=str(mysql_data.get("charset", "utf8mb4")),
        connect_timeout=float(mysql_data.get("connect_timeout", 10.0)),
        autocommit=bool(mysql_data.get("autocommit", False)),
    )
    browser_data = data.get("browser") if isinstance(data.get("browser"), dict) else {}
    command = browser_data.get("mcp_command", DEFAULT_MCP_COMMAND)
    if isinstance(command, str):
        command = tuple(command.split())
    elif isinstance(command, list):
        command = tuple(str(item) for item in command if str(item).strip())
    else:
        command = DEFAULT_MCP_COMMAND
    browser = BrowserConfig(
        cdp_url=str(browser_data.get("cdp_url", DEFAULT_CDP_URL)),
        profile_dir=config_path_value(browser_data.get("profile_dir"), DEFAULT_PROFILE_DIR),
        mcp_command=command,
        mcp_timeout=float(browser_data.get("mcp_timeout", 30.0)),
        headless=bool(browser_data.get("headless", False)),
        max_scrolls=int(browser_data.get("max_scrolls", 10000)),
        batch_size=int(browser_data.get("batch_size", 20)),
        wait_ms=int(browser_data.get("wait_ms", 1200)),
        max_retries=int(browser_data.get("max_retries", 3)),
        navigate_tool=str(browser_data.get("navigate_tool", "navigate_page")),
        evaluate_tool=str(browser_data.get("evaluate_tool", "evaluate_script")),
        new_page_tool=str(browser_data.get("new_page_tool", "new_page")),
        select_page_tool=str(browser_data.get("select_page_tool", "select_page")),
        close_page_tool=str(browser_data.get("close_page_tool", "close_page")),
        list_pages_tool=str(browser_data.get("list_pages_tool", "list_pages")),
    )
    vault = config_path_value(obsidian.get("vault"), Path(".")) if obsidian.get("vault") else None
    return AppConfig(
        database=config_path_value(data.get("database"), DEFAULT_DATABASE),
        mysql=mysql,
        vault=vault,
        media_root=config_path_value(data.get("media_root"), DEFAULT_MEDIA_ROOT),
        browser=browser,
        obsidian_folder=str(obsidian.get("folder", "X Clips")),
        users=users,
    )
