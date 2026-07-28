#!/Users/rgwei/anaconda3/bin/python
"""Read and copy files in the local macOS iCloud Drive directory."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path


DEFAULT_ICLOUD_ROOT = (
    Path.home() / "Library" / "Mobile Documents" / "com~apple~CloudDocs"
)
ICLOUD_ROOT_ENV = "ICLOUD_DRIVE_PATH"


class ICloudDriveError(Exception):
    """An expected error that can be shown directly to a CLI user."""


def get_icloud_root(explicit_root: Path | None = None) -> Path:
    configured_root = explicit_root
    if configured_root is None and os.environ.get(ICLOUD_ROOT_ENV):
        configured_root = Path(os.environ[ICLOUD_ROOT_ENV])

    root = (configured_root or DEFAULT_ICLOUD_ROOT).expanduser().resolve(strict=False)
    if not root.exists():
        raise ICloudDriveError(
            f"iCloud Drive directory was not found: {root}\n"
            "Enable iCloud Drive in System Settings, or pass --root."
        )
    if not root.is_dir():
        raise ICloudDriveError(f"iCloud Drive path is not a directory: {root}")
    return root


def resolve_inside(
    root: Path, relative_path: str | Path, *, must_exist: bool = False
) -> Path:
    """Resolve an iCloud-relative path while preventing escapes from root."""
    root = root.expanduser().resolve(strict=False)
    relative = Path(relative_path)
    if relative.is_absolute():
        raise ICloudDriveError(
            f"Use a path relative to iCloud Drive, not an absolute path: {relative}"
        )

    candidate = (root / relative).resolve(strict=False)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ICloudDriveError(
            f"Path points outside iCloud Drive and was rejected: {relative}"
        ) from exc

    if must_exist and not candidate.exists():
        raise ICloudDriveError(f"iCloud item does not exist: {relative}")
    return candidate


def check_not_recursive(source: Path, destination: Path) -> None:
    if source == destination:
        raise ICloudDriveError("Source and destination are the same path.")
    if source.is_dir() and destination.is_relative_to(source):
        raise ICloudDriveError("Cannot copy a directory into itself.")


def copy_item(source: Path, destination: Path, *, overwrite: bool) -> Path:
    """Copy one file or directory and return its final destination."""
    source = source.expanduser().resolve(strict=False)
    if not source.exists():
        raise ICloudDriveError(f"Source does not exist: {source}")

    destination = destination.expanduser().resolve(strict=False)
    if destination.exists() and destination.is_dir() and source.is_file():
        destination = destination / source.name

    check_not_recursive(source, destination)

    if destination.exists() and not overwrite:
        raise ICloudDriveError(
            f"Destination already exists: {destination}\n"
            "Pass --overwrite to replace or merge it."
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        if destination.exists() and not destination.is_dir():
            raise ICloudDriveError(
                f"Cannot copy a directory over a file: {destination}"
            )
        shutil.copytree(source, destination, dirs_exist_ok=overwrite)
    elif source.is_file():
        if destination.exists() and destination.is_dir():
            raise ICloudDriveError(
                f"Cannot copy a file over a directory: {destination}"
            )
        shutil.copy2(source, destination)
    else:
        raise ICloudDriveError(f"Source is not a regular file or directory: {source}")

    return destination


def upload(
    root: Path,
    source: Path,
    destination: str | Path | None,
    *,
    overwrite: bool,
) -> Path:
    root = root.expanduser().resolve(strict=False)
    source = source.expanduser().resolve(strict=False)
    relative_destination = destination if destination is not None else source.name
    target = resolve_inside(root, relative_destination)
    result = copy_item(source, target, overwrite=overwrite)

    # copy_item may append source.name when target is an existing directory.
    try:
        result.relative_to(root)
    except ValueError as exc:
        raise ICloudDriveError("Resolved upload destination escaped iCloud Drive.") from exc
    return result


def download(
    root: Path,
    source: str | Path,
    destination: Path | None,
    *,
    overwrite: bool,
) -> Path:
    root = root.expanduser().resolve(strict=False)
    cloud_source = resolve_inside(root, source, must_exist=True)
    if cloud_source == root:
        raise ICloudDriveError("Choose a file or folder inside iCloud Drive.")

    local_destination = destination or (Path.cwd() / cloud_source.name)
    return copy_item(cloud_source, local_destination, overwrite=overwrite)


def list_items(root: Path, relative_path: str | Path, *, recursive: bool) -> list[dict]:
    target = resolve_inside(root, relative_path, must_exist=True)
    if not target.is_dir():
        raise ICloudDriveError(f"Not a directory: {relative_path}")

    paths = target.rglob("*") if recursive else target.iterdir()
    entries: list[dict] = []
    for path in sorted(paths, key=lambda item: str(item).casefold()):
        stat = path.stat()
        entries.append(
            {
                "path": str(path.relative_to(target)),
                "type": "directory" if path.is_dir() else "file",
                "size": None if path.is_dir() else stat.st_size,
                "modified": stat.st_mtime,
            }
        )
    return entries


def read_file(
    root: Path,
    relative_path: str | Path,
    *,
    encoding: str,
    max_bytes: int,
) -> str:
    target = resolve_inside(root, relative_path, must_exist=True)
    if not target.is_file():
        raise ICloudDriveError(f"Not a file: {relative_path}")

    size = target.stat().st_size
    if max_bytes > 0 and size > max_bytes:
        raise ICloudDriveError(
            f"File is {size} bytes, above the read limit of {max_bytes} bytes.\n"
            "Use --max-bytes 0 for no limit, or use download for binary/large files."
        )
    try:
        return target.read_text(encoding=encoding)
    except UnicodeDecodeError as exc:
        raise ICloudDriveError(
            f"File is not valid {encoding} text. Use --encoding or download it instead."
        ) from exc


def format_permission_error(root: Path) -> str:
    return (
        f"macOS denied access to iCloud Drive: {root}\n"
        "Open System Settings > Privacy & Security > Files and Folders "
        "(or Full Disk Access), allow your terminal/Python app, then retry."
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read and copy files through the local macOS iCloud Drive folder."
    )
    parser.add_argument(
        "--root",
        type=Path,
        help=(
            "Override the iCloud Drive root. Defaults to ICLOUD_DRIVE_PATH or the "
            "standard macOS iCloud Drive location."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("status", help="Show the detected iCloud Drive path.")

    list_parser = subparsers.add_parser("list", help="List iCloud files and folders.")
    list_parser.add_argument("path", nargs="?", default=".", help="iCloud-relative folder.")
    list_parser.add_argument("-r", "--recursive", action="store_true")
    list_parser.add_argument("--json", action="store_true", dest="as_json")

    read_parser = subparsers.add_parser("read", help="Print a text file from iCloud.")
    read_parser.add_argument("path", help="iCloud-relative file path.")
    read_parser.add_argument("--encoding", default="utf-8")
    read_parser.add_argument(
        "--max-bytes",
        type=int,
        default=10 * 1024 * 1024,
        help="Maximum size to print; 0 disables the limit (default: 10 MiB).",
    )

    upload_parser = subparsers.add_parser(
        "upload", help="Copy a local file or folder into iCloud."
    )
    upload_parser.add_argument("source", type=Path, help="Local source path.")
    upload_parser.add_argument(
        "destination",
        nargs="?",
        help="iCloud-relative destination; defaults to the source name.",
    )
    upload_parser.add_argument("--overwrite", action="store_true")

    download_parser = subparsers.add_parser(
        "download", help="Copy an iCloud file or folder to the local filesystem."
    )
    download_parser.add_argument("source", help="iCloud-relative source path.")
    download_parser.add_argument(
        "destination", nargs="?", type=Path, help="Local destination path."
    )
    download_parser.add_argument("--overwrite", action="store_true")
    return parser


def run(args: argparse.Namespace, root: Path) -> int:
    if args.command == "status":
        # Accessing one entry makes permission failures visible in status output.
        next(root.iterdir(), None)
        print(f"iCloud Drive: {root}")
        print("Access: OK")
        return 0

    if args.command == "list":
        entries = list_items(root, args.path, recursive=args.recursive)
        if args.as_json:
            print(json.dumps(entries, ensure_ascii=False, indent=2))
        else:
            for entry in entries:
                suffix = "/" if entry["type"] == "directory" else ""
                print(f"{entry['path']}{suffix}")
        return 0

    if args.command == "read":
        if args.max_bytes < 0:
            raise ICloudDriveError("--max-bytes must be zero or greater.")
        content = read_file(
            root, args.path, encoding=args.encoding, max_bytes=args.max_bytes
        )
        sys.stdout.write(content)
        if content and not content.endswith("\n"):
            sys.stdout.write("\n")
        return 0

    if args.command == "upload":
        destination = upload(
            root,
            args.source,
            args.destination,
            overwrite=args.overwrite,
        )
        print(destination)
        return 0

    if args.command == "download":
        destination = download(
            root,
            args.source,
            args.destination,
            overwrite=args.overwrite,
        )
        print(destination)
        return 0

    raise ICloudDriveError(f"Unknown command: {args.command}")


def main() -> int:
    args = build_parser().parse_args()
    root: Path | None = None
    try:
        root = get_icloud_root(args.root)
        return run(args, root)
    except ICloudDriveError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except PermissionError:
        denied_root = root or (args.root or DEFAULT_ICLOUD_ROOT).expanduser()
        print(f"Error: {format_permission_error(denied_root)}", file=sys.stderr)
        return 2
    except BrokenPipeError:
        return 0
    except OSError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
