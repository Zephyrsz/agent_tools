"""JSON project configuration with CLI-overridable defaults."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import normalize_handle


DEFAULT_DATABASE = Path("~/.local/share/x_ingest/posts.sqlite3")


@dataclass(frozen=True)
class UserConfig:
    handle: str
    relation: str = "own_post"
    enabled: bool = True


@dataclass(frozen=True)
class AppConfig:
    database: Path = DEFAULT_DATABASE
    vault: Path | None = None
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
    vault = Path(obsidian["vault"]).expanduser() if obsidian.get("vault") else None
    return AppConfig(
        database=Path(data.get("database", DEFAULT_DATABASE)).expanduser(),
        vault=vault,
        obsidian_folder=str(obsidian.get("folder", "X Clips")),
        users=users,
    )
