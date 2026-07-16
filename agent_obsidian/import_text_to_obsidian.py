#!/usr/bin/env python3
"""
Import a local text file into an Obsidian vault as a Markdown note.

Usage:
  python3 agent_obsidian/import_text_to_obsidian.py agent_obsidian/note1.txt \
    --title "Obsidian Vault 与本地笔记读取方式"

If --vault is omitted, the script reads Obsidian's local config and uses the
only configured vault. If multiple vaults exist, pass --vault explicitly.
"""

from __future__ import annotations

import argparse
import json
import platform
import re
from pathlib import Path


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


def build_markdown(title: str, body: str) -> str:
    normalized_body = body.strip()
    if normalized_body.startswith("# "):
        return normalized_body + "\n"
    return f"# {title}\n\n{normalized_body}\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import a text file into Obsidian.")
    parser.add_argument("source", type=Path, help="Source text file.")
    parser.add_argument("--title", required=True, help="Markdown note title.")
    parser.add_argument("--vault", type=Path, help="Obsidian vault path.")
    parser.add_argument(
        "--folder",
        default="",
        help="Optional folder inside the vault, for example 'Inbox'.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_path = args.source.expanduser().resolve()
    if not source_path.is_file():
        raise SystemExit(f"Source file does not exist: {source_path}")

    vault_path = choose_vault(args.vault)
    folder = Path(args.folder.strip("/")) if args.folder else Path()
    target_dir = vault_path / folder
    target_dir.mkdir(parents=True, exist_ok=True)

    body = source_path.read_text(encoding="utf-8")
    markdown = build_markdown(args.title, body)
    destination = unique_destination(target_dir / f"{filename_from_title(args.title)}.md")
    destination.write_text(markdown, encoding="utf-8")

    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
