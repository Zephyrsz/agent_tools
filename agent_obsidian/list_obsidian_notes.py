#!/usr/bin/env python3
"""
List local Obsidian notes.

Usage:
  python3 agent_obsidian/list_obsidian_notes.py
  python3 agent_obsidian/list_obsidian_notes.py --vault /path/to/MyVault
  python3 agent_obsidian/list_obsidian_notes.py --json

By default this script reads Obsidian's local config file on macOS and lists
Markdown files in all known vaults. You can also pass --vault explicitly.
"""

from __future__ import annotations

import argparse
import json
import platform
from pathlib import Path
from typing import Iterable


def obsidian_config_path() -> Path:
    """Return the usual Obsidian config path for the current operating system."""
    system = platform.system()
    home = Path.home()

    if system == "Darwin":
        return home / "Library" / "Application Support" / "obsidian" / "obsidian.json"
    if system == "Windows":
        return home / "AppData" / "Roaming" / "obsidian" / "obsidian.json"

    return home / ".config" / "obsidian" / "obsidian.json"


def load_vaults_from_obsidian_config(config_path: Path) -> list[Path]:
    """Load vault directories recorded by Obsidian."""
    if not config_path.exists():
        return []

    data = json.loads(config_path.read_text(encoding="utf-8"))
    vaults = data.get("vaults", {})
    paths: list[Path] = []

    for vault in vaults.values():
        path = vault.get("path")
        if path:
            paths.append(Path(path).expanduser())

    return paths


def is_obsidian_vault(path: Path) -> bool:
    """A normal Obsidian vault has a .obsidian directory at its root."""
    return path.is_dir() and (path / ".obsidian").is_dir()


def iter_markdown_notes(vault_path: Path) -> Iterable[Path]:
    """Yield Markdown notes under a vault, skipping Obsidian internals."""
    for path in sorted(vault_path.rglob("*.md")):
        if ".obsidian" not in path.relative_to(vault_path).parts:
            yield path


def note_record(vault_path: Path, note_path: Path) -> dict[str, str]:
    return {
        "vault": str(vault_path),
        "path": str(note_path),
        "relative_path": str(note_path.relative_to(vault_path)),
        "title": note_path.stem,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="List local Obsidian Markdown notes.")
    parser.add_argument(
        "--vault",
        action="append",
        type=Path,
        help="Obsidian vault path. Can be passed more than once.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON instead of text.",
    )
    parser.add_argument(
        "--allow-non-vault",
        action="store_true",
        help="List Markdown files even if the directory does not contain .obsidian.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    vault_paths = [path.expanduser() for path in args.vault or []]
    if not vault_paths:
        vault_paths = load_vaults_from_obsidian_config(obsidian_config_path())

    records: list[dict[str, str]] = []
    skipped: list[Path] = []

    for vault_path in vault_paths:
        vault_path = vault_path.resolve()
        if not args.allow_non_vault and not is_obsidian_vault(vault_path):
            skipped.append(vault_path)
            continue

        for note_path in iter_markdown_notes(vault_path):
            records.append(note_record(vault_path, note_path))

    if args.json:
        print(json.dumps(records, ensure_ascii=False, indent=2))
    else:
        if not records:
            print("No Obsidian notes found.")
        for record in records:
            print(f"{record['vault']} :: {record['relative_path']}")

        if skipped:
            print("\nSkipped non-vault directories:")
            for path in skipped:
                print(f"- {path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
