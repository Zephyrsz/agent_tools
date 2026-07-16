#!/usr/bin/env python3
"""
Save extracted X/Twitter posts into an Obsidian note.

This script does not fetch X pages. It consumes JSON produced by a Chrome
DevTools MCP extractor and writes Markdown into an Obsidian vault.

Usage:
  python3 agent_obsidian/save_x_posts_to_obsidian.py x_posts.json
  python3 agent_obsidian/save_x_posts_to_obsidian.py x_posts.json --title "Andrew Ng recent posts"
  python3 agent_obsidian/save_x_posts_to_obsidian.py x_posts.json --per-post
"""

from __future__ import annotations

import argparse
import json
import platform
import re
from datetime import datetime
from pathlib import Path
from typing import Any


def obsidian_config_path() -> Path:
    system = platform.system()
    home = Path.home()

    if system == "Darwin":
        return home / "Library" / "Application Support" / "obsidian" / "obsidian.json"
    if system == "Windows":
        return home / "AppData" / "Roaming" / "obsidian" / "obsidian.json"

    return home / ".config" / "obsidian" / "obsidian.json"


def load_vault_paths() -> list[Path]:
    config_path = obsidian_config_path()
    if not config_path.exists():
        return []

    data = json.loads(config_path.read_text(encoding="utf-8"))
    paths: list[Path] = []
    for vault in data.get("vaults", {}).values():
        path = vault.get("path")
        if path:
            paths.append(Path(path).expanduser())
    return paths


def choose_vault(explicit_vault: Path | None) -> Path:
    if explicit_vault is not None:
        vault_path = explicit_vault.expanduser().resolve()
    else:
        vault_paths = [path.expanduser().resolve() for path in load_vault_paths()]
        existing_vaults = [path for path in vault_paths if path.is_dir()]
        if len(existing_vaults) != 1:
            raise SystemExit(
                "Could not choose a vault automatically. Pass --vault /path/to/vault."
            )
        vault_path = existing_vaults[0]

    if not vault_path.is_dir():
        raise SystemExit(f"Vault does not exist: {vault_path}")
    if not (vault_path / ".obsidian").is_dir():
        raise SystemExit(f"Directory is not an Obsidian vault: {vault_path}")

    return vault_path


def filename_from_title(title: str) -> str:
    filename = re.sub(r'[\\/:*?"<>|]+', "-", title).strip()
    filename = re.sub(r"\s+", " ", filename)
    return filename or "Untitled"


def unique_destination(path: Path) -> Path:
    if not path.exists():
        return path

    for index in range(2, 1000):
        candidate = path.with_name(f"{path.stem} {index}{path.suffix}")
        if not candidate.exists():
            return candidate

    raise SystemExit(f"Too many existing files with similar name: {path}")


def load_posts(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return {"posts": data}
    if isinstance(data, dict) and isinstance(data.get("posts"), list):
        return data
    raise SystemExit("Input JSON must be a list of posts or an object with a posts list.")


def markdown_quote(text: str) -> str:
    lines = text.strip().splitlines()
    return "\n".join(f"> {line}" if line else ">" for line in lines)


def post_author_name(post: dict[str, Any]) -> str:
    author = post.get("author", {})
    name = str(author.get("displayName", "")).strip()
    handle = str(author.get("handle", "")).strip().lstrip("@")
    return name or handle or "Unknown Author"


def post_id_from_url(url: str) -> str:
    match = re.search(r"/status/(\d+)", url)
    return match.group(1) if match else ""


def post_date(post: dict[str, Any]) -> str:
    timestamp = str(post.get("timestamp", "")).strip()
    if not timestamp:
        return datetime.now().strftime("%Y-%m-%d")
    parsed = None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%a %b %d %H:%M:%S %z %Y"):
        try:
            parsed = datetime.strptime(timestamp, fmt)
            break
        except ValueError:
            continue
    if parsed is None:
        return timestamp[:10] if len(timestamp) >= 10 else datetime.now().strftime("%Y-%m-%d")
    return parsed.strftime("%Y-%m-%d")


def infer_title(data: dict[str, Any]) -> str:
    posts = data.get("posts", [])
    first = posts[0] if posts else {}
    handle = first.get("author", {}).get("handle") if isinstance(first, dict) else ""
    date = datetime.now().strftime("%Y-%m-%d")
    if handle:
        return f"{handle} recent X posts - {date}"
    return f"X posts - {date}"


def append_images(lines: list[str], post: dict[str, Any], post_label: str) -> None:
    images = post.get("images", [])
    if not images:
        return

    lines.extend(["", "Images:"])
    for image_index, image in enumerate(images, start=1):
        if isinstance(image, str):
            image_url = image
            alt = f"{post_label} image {image_index}"
        else:
            image_url = str(image.get("url", "")).strip()
            alt = str(image.get("alt", "")).strip() or f"{post_label} image {image_index}"
        if image_url:
            lines.append(f"![{alt}]({image_url})")


def render_markdown(data: dict[str, Any], title: str, include_sources: bool) -> str:
    posts = data.get("posts", [])
    captured_at = data.get("capturedAt", "")
    source_page = data.get("sourcePage", "")

    lines = [f"# {title}", ""]
    if captured_at:
        lines.append(f"Captured: {captured_at}")
    if source_page:
        lines.append(f"Source page: {source_page}")
    if captured_at or source_page:
        lines.append("")

    for index, post in enumerate(posts, start=1):
        text = str(post.get("text", "")).strip()
        if not text:
            continue

        lines.extend([f"## Post {index}", "", markdown_quote(text)])
        append_images(lines, post, f"Post {index}")
        if include_sources and post.get("url"):
            lines.extend(["", f"Source: {post['url']}"])
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def render_single_post_markdown(
    post: dict[str, Any],
    captured_at: str,
    include_sources: bool,
) -> str:
    author_name = post_author_name(post)
    date = post_date(post)
    title = f"{author_name} X Post - {date}"
    text = str(post.get("text", "")).strip()

    lines = [f"# {title}", ""]
    lines.append(f"Author: {author_name}")
    if post.get("timestamp"):
        lines.append(f"Published: {post['timestamp']}")
    if captured_at:
        lines.append(f"Captured: {captured_at}")
    lines.append("")

    if text:
        lines.append(markdown_quote(text))

    append_images(lines, post, "Post")

    if include_sources and post.get("url"):
        lines.extend(["", f"Source: {post['url']}"])

    return "\n".join(lines).rstrip() + "\n"


def write_per_post_markdown(
    data: dict[str, Any],
    vault_path: Path,
    root_folder: str,
    include_sources: bool,
    overwrite: bool,
) -> list[Path]:
    posts = data.get("posts", [])
    captured_at = str(data.get("capturedAt", "")).strip()
    destinations: list[Path] = []

    for index, post in enumerate(posts, start=1):
        if not isinstance(post, dict):
            continue
        if post.get("hasVideo"):
            continue
        text = str(post.get("text", "")).strip()
        if not text:
            continue

        author_name = post_author_name(post)
        target_dir = vault_path / Path(root_folder.strip("/")) / filename_from_title(author_name) / "raw"
        target_dir.mkdir(parents=True, exist_ok=True)

        status_id = post_id_from_url(str(post.get("url", "")))
        suffix = status_id or f"post-{index}"
        destination = target_dir / f"{post_date(post)}-{suffix}.md"
        if not overwrite:
            destination = unique_destination(destination)

        destination.write_text(
            render_single_post_markdown(post, captured_at, include_sources),
            encoding="utf-8",
        )
        destinations.append(destination)

    return destinations


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Save extracted X posts into Obsidian.")
    parser.add_argument("json_file", type=Path, help="JSON file produced by the extractor.")
    parser.add_argument("--vault", type=Path, help="Obsidian vault path.")
    parser.add_argument("--folder", default="X Clips", help="Folder inside the vault.")
    parser.add_argument("--title", help="Destination note title.")
    parser.add_argument(
        "--per-post",
        action="store_true",
        help="Write one Markdown file per post under X Clips/{Author}/raw.",
    )
    parser.add_argument(
        "--include-sources",
        action="store_true",
        help="Include each post source URL under the quoted text.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite an existing destination file instead of creating a numbered copy.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    json_path = args.json_file.expanduser().resolve()
    if not json_path.is_file():
        raise SystemExit(f"JSON file does not exist: {json_path}")

    data = load_posts(json_path)
    vault_path = choose_vault(args.vault)

    if args.per_post:
        destinations = write_per_post_markdown(
            data,
            vault_path,
            args.folder,
            args.include_sources,
            args.overwrite,
        )
        for destination in destinations:
            print(destination)
        return 0

    title = args.title or infer_title(data)
    markdown = render_markdown(data, title, args.include_sources)

    folder = Path(args.folder.strip("/")) if args.folder else Path()
    target_dir = vault_path / folder
    target_dir.mkdir(parents=True, exist_ok=True)

    destination = target_dir / f"{filename_from_title(title)}.md"
    if not args.overwrite:
        destination = unique_destination(destination)

    destination.write_text(markdown, encoding="utf-8")
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
