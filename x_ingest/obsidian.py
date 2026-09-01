"""Export canonical posts from SQLite into stable Obsidian Markdown files."""

from __future__ import annotations

import json
import platform
import re
from pathlib import Path
from typing import Any

from .repository import PostRepository


def obsidian_config_path() -> Path:
    home = Path.home()
    if platform.system() == "Darwin":
        return home / "Library" / "Application Support" / "obsidian" / "obsidian.json"
    if platform.system() == "Windows":
        return home / "AppData" / "Roaming" / "obsidian" / "obsidian.json"
    return home / ".config" / "obsidian" / "obsidian.json"


def configured_vaults() -> list[Path]:
    config = obsidian_config_path()
    if not config.exists():
        return []
    data = json.loads(config.read_text(encoding="utf-8"))
    return [
        Path(item["path"]).expanduser()
        for item in data.get("vaults", {}).values()
        if item.get("path")
    ]


def resolve_vault(explicit: str | Path | None) -> Path:
    if explicit:
        vault = Path(explicit).expanduser().resolve()
    else:
        candidates = [path.resolve() for path in configured_vaults() if path.is_dir()]
        if len(candidates) != 1:
            raise ValueError("could not select one Obsidian vault; pass --vault")
        vault = candidates[0]
    if not vault.is_dir() or not (vault / ".obsidian").is_dir():
        raise ValueError(f"not an Obsidian vault: {vault}")
    return vault


def safe_name(value: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]+', "-", value).strip()
    return re.sub(r"\s+", " ", name) or "Unknown Author"


def markdown_quote(text: str) -> str:
    return "\n".join(f"> {line}" if line else ">" for line in text.strip().splitlines())


def post_filename(post: dict[str, Any]) -> str:
    timestamp = str(post["created_at"]).replace(":", "-")
    return f"{timestamp}-{post['post_id']}.md"


def render_post(post: dict[str, Any], media: list[dict[str, Any]]) -> str:
    display_name = (
        post.get("author_display_name") or post.get("author_handle") or "Unknown Author"
    )
    lines = [
        "---",
        "source: x",
        f'post_id: "{post["post_id"]}"',
        f'author_handle: "{post["author_handle"]}"',
        f'published: "{post["created_at"]}"',
        f'url: "{post["url"]}"',
        f'post_kind: "{post["post_kind"]}"',
        f"has_video: {str(bool(post['has_video'])).lower()}",
        f"is_pinned: {str(bool(post['is_pinned'])).lower()}",
        "---",
        "",
        f"# {display_name} X Post - {post['created_at']}",
        "",
    ]
    if post.get("text"):
        lines.append(markdown_quote(str(post["text"])))
    if media:
        lines.extend(["", "## Media", ""])
        for item in media:
            target = item.get("local_path") or item["remote_url"]
            alt = (
                item.get("alt_text")
                or f"Post {post['post_id']} media {item['ordinal']}"
            )
            if item.get("media_type") == "image":
                lines.append(f"![{alt}]({target})")
            else:
                lines.append(f"- [{item['media_type']}]({target})")
    lines.extend(["", f"Source: {post['url']}"])
    return "\n".join(lines).rstrip() + "\n"


def export_posts(
    store: PostRepository,
    *,
    vault: str | Path,
    handle: str,
    folder: str = "X Clips",
    after: str | None = None,
    after_id: str | None = None,
    before: str | None = None,
    before_id: str | None = None,
    limit: int = 10000,
) -> list[Path]:
    vault_path = resolve_vault(vault)
    posts = store.query_posts(
        handle=handle,
        after=after,
        after_id=after_id,
        before=before,
        before_id=before_id,
        order="asc",
        limit=limit,
    )
    written: list[Path] = []
    for post in posts:
        author_dir = safe_name(post.get("author_display_name") or post["author_handle"])
        destination = (
            vault_path / folder.strip("/") / author_dir / "raw" / post_filename(post)
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        content = render_post(post, store.get_media(post["post_id"]))
        if (
            not destination.exists()
            or destination.read_text(encoding="utf-8") != content
        ):
            destination.write_text(content, encoding="utf-8")
            written.append(destination)
        store.set_obsidian_path(post["post_id"], destination.relative_to(vault_path))
    return written
